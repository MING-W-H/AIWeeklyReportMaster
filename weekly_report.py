# -*- coding: utf-8 -*-
"""
AI 周报生成器 - 多 LLM Provider 支持（MiniMax / DeepSeek / OpenCode / Qwen）

处理 CRM 下载的单个工时 Excel（或本地 excel_folder 目录中最新修改的一个文件），
提取 B(任务名称)/D(项目/需求)/H(工作描述) 三列内容，单文件内去重后交由 AI 总结整理，
返回一段可设置格式的周报文本，经钉钉人工审核后通过钉钉和腾讯企业邮箱发送。

支持四种 AI Provider（均使用 OpenAI 兼容接口）：
    - minimax : MiniMax M3 模型 (https://api.minimaxi.com/v1/chat/completions)
    - deepseek: DeepSeek V4 模型 (https://api.deepseek.com/chat/completions)
    - opencode: OpenCode Zen 网关 (https://opencode.ai/zen/v1/chat/completions)
    - qwen    : 通义千问 Qwen 3.8 Max (https://dashscope.aliyuncs.com/compatible-mode/v1)

使用方式：
    1. 首次运行会自动生成 config.json 模板，请填入对应 provider 的 API Key
    2. python weekly_report.py                              # 使用默认 provider
    3. python weekly_report.py --provider deepseek          # 切换 provider
    4. python weekly_report.py --provider opencode --thinking  # 启用思考模式
    5. python weekly_report.py --no-email                    # 跳过邮件发送
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import warnings
from pathlib import Path
from typing import Optional

# 强制 stdout/stderr 使用 UTF-8 编码，避免 Windows PowerShell 中文乱码
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 抑制 openpyxl 读取部分 Excel 时产生的样式警告（不影响数据读取）
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

from config_manager import PROVIDER_PRESETS, load_config, validate_required_config
from crm_downloader import download_workhour_excel
from dingtalk_confirmer import send_dingtalk_report, send_failure_alert, wait_for_confirmation
from email_sender import send_report_email
from excel_aggregator import aggregate_excel_content
from holiday_checker import should_skip_execution
from llm_client import FORMAT_TEMPLATES, build_prompt, call_llm_api
from logger import get_logger, init_logging
from output_resolver import render_template, resolve_output_path

logger = get_logger(__name__)

LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".weekly_report.lock")


class ErrorCode:
    """统一的错误码常量"""
    SUCCESS = 0
    LOCK_FAILED = 10
    CRM_ERROR = 1
    LLM_ERROR = 2
    EMAIL_ERROR = 3
    DINGTALK_ERROR = 4
    CONFIG_ERROR = 11


def _acquire_lock() -> bool:
    """单实例锁：防止多个进程同时运行导致钉钉 Stream 连接互相抢占。

    锁文件记录运行中进程的 PID；若 PID 仍存活则拒绝启动。
    进程正常退出时由 finally 释放，异常退出时 PID 已死、下次运行自动接管。
    返回 True 表示成功获取锁（或锁初始化失败但不影响运行）。
    """
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                old_pid = int(f.read().strip() or "0")
            if old_pid and _pid_alive(old_pid):
                logger.error("已有周报进程 (PID %s) 正在运行，请勿重复启动。", old_pid)
                logger.info("若确认该进程已结束，请删除文件: .weekly_report.lock 后重试")
                return False
        with open(LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except (OSError, ValueError) as e:
        logger.warning("单实例锁初始化失败（不影响运行）: %s", e)
    return True


def _release_lock() -> None:
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    """检查进程是否存活（跨平台）。

    注意：Windows 上 os.kill(pid, 0) 会调用 TerminateProcess 直接杀死目标进程，
    不能用作存活探测，这里改用 OpenProcess + GetExitCodeProcess 查询。
    """
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            # ctypes 探测失败时保守返回 False（视为已退出，允许锁自动接管）
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except Exception:
        return False
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI 周报生成器 (多 LLM Provider 支持)")
    parser.add_argument("--provider", choices=list(PROVIDER_PRESETS.keys()),
                        help="选择 AI provider: minimax | deepseek | opencode | qwen")
    parser.add_argument("--model", help="覆盖 provider 的 model 名称")
    parser.add_argument("--format", choices=list(FORMAT_TEMPLATES.keys()) + ["custom"],
                        help="覆盖 config.json 中的 output_format")
    parser.add_argument("--output", help="输出文件路径（覆盖 config.json 中的 output_file）")
    parser.add_argument("--output-folder", help="周报输出文件夹路径（覆盖 config.json 中的 output_folder）")
    parser.add_argument("--folder", help="Excel 文件夹路径（覆盖 config.json 中的 excel_folder）")
    parser.add_argument("--crm-start", help="CRM 下载起始日期 (YYYY-MM-DD)，默认上一周周一")
    parser.add_argument("--crm-finish", help="CRM 下载结束日期 (YYYY-MM-DD)，默认上一周周五")
    parser.add_argument("--no-crm", action="store_true",
                        help="跳过 CRM 接口下载，直接使用 excel_folder 下的本地 Excel 文件")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅汇总 Excel 内容并打印，不调用 API")
    parser.add_argument("--thinking", action="store_true",
                        help="启用思考模式 (DeepSeek/MiniMax 生效)")
    parser.add_argument("--debug", action="store_true",
                        help="打印详细异常调用栈")
    parser.add_argument("--no-email", action="store_true",
                        help="跳过邮件发送（即使 config.json 中 email.enabled=true）")
    parser.add_argument("--no-confirm", action="store_true",
                        help="跳过钉钉人工审核，AI 生成后直接发送（钉钉+邮件）")
    parser.add_argument("--force", action="store_true",
                        help="强制执行，跳过节假日检查（节假日也会执行）")
    return parser.parse_args()


def apply_args_to_config(args: argparse.Namespace, config: dict) -> None:
    """将命令行参数覆盖到配置字典中"""
    if args.provider:
        config["provider"] = args.provider
    if args.model:
        config["providers"][config["provider"]]["model"] = args.model
    if args.format:
        config["output_format"] = args.format
    if args.output:
        config["output_file"] = args.output
    if args.output_folder:
        config["output_folder"] = args.output_folder
    if args.folder:
        config["excel_folder"] = args.folder
    if args.thinking:
        config["thinking_enabled"] = True


def init_run_logging(config: dict, debug: bool):
    """初始化日志系统，返回日志文件路径"""
    if config.get("output_file"):
        run_label = Path(config["output_file"]).stem
    else:
        run_label = render_template(config.get("output_file_template") or "Vue{date}周报")
    log_path = init_logging(run_label, debug=debug)
    logger.info("运行日志已保存至: %s", log_path)
    return log_path


def check_holiday_skip(force: bool, log_path) -> Optional[int]:
    """检查是否应该跳过执行（节假日/周末）

    Returns:
        错误码（0 表示跳过执行，应直接返回）或 None（继续执行）
    """
    if force:
        return None
    should_skip, reason = should_skip_execution()
    if should_skip:
        logger.info(reason)
        logger.info("如需强制执行，请使用: python weekly_report.py --force")
        logger.info("运行日志: %s", log_path)
        return ErrorCode.SUCCESS
    return None


def download_crm_if_enabled(
    config: dict, args: argparse.Namespace
) -> tuple[Optional[str], Optional[int]]:
    """根据配置和参数决定是否下载 CRM 工时 Excel

    Returns:
        (downloaded_path, error_code): 成功返回路径和 None，失败返回 None 和错误码
    """
    crm_cfg = config.get("crm", {})
    if not crm_cfg.get("enabled") or args.no_crm:
        if args.no_crm:
            logger.info("已跳过 CRM 接口下载（--no-crm），使用本地 Excel 文件")
        else:
            logger.info("CRM 接口未启用，使用本地 excel_folder 下的 Excel 文件")
        return None, None

    try:
        logger.info("=" * 60)
        logger.info("步骤 1/3: 从 CRM 接口下载工时 Excel")
        logger.info("=" * 60)
        downloaded_path = download_workhour_excel(
            config,
            start_date=args.crm_start,
            finish_date=args.crm_finish,
        )
        return downloaded_path, None
    except ValueError as e:
        logger.error("CRM 配置错误: %s", e)
        return None, ErrorCode.CRM_ERROR
    except RuntimeError as e:
        logger.error("CRM 接口下载失败: %s", e)
        send_failure_alert(config, f"CRM 下载失败: {e}")
        if args.debug:
            logger.debug("CRM 下载异常堆栈:", exc_info=True)
        logger.info("可使用 --no-crm 跳过下载，直接使用本地 Excel 文件")
        return None, ErrorCode.CRM_ERROR


def generate_report_via_llm(
    prompt: str, config: dict, debug: bool
) -> tuple[Optional[str], Optional[int]]:
    """调用 LLM API 生成周报（支持 provider 自动降级）

    Returns:
        (report_text, error_code): 成功返回周报文本和 None，失败返回 None 和错误码
    """
    providers = config.get("providers", {})
    current_provider = config["provider"]
    # 构建降级顺序：当前 provider 优先，其余已配置 api_key 的 provider 按序
    fallback_order = [current_provider] + [
        p for p in providers
        if p != current_provider and providers[p].get("api_key", "").strip()
    ]
    report_text = None
    last_error = None
    for idx, provider_name in enumerate(fallback_order):
        try:
            config["provider"] = provider_name
            report_text = call_llm_api(prompt, config)
            break  # 成功后跳出
        except ValueError as e:
            # 配置类错误（如 api_key 缺失、provider 未知）
            logger.error("%s 配置错误: %s", provider_name, e)
            if idx < len(fallback_order) - 1:
                logger.info("尝试切换到下一个 provider: %s", fallback_order[idx + 1])
                continue
            # 最后一个 provider 也配置错误
            return None, ErrorCode.LLM_ERROR
        except RuntimeError as e:
            logger.warning("%s 调用失败: %s", provider_name, e)
            last_error = e
            if idx < len(fallback_order) - 1:
                logger.info("尝试切换到下一个 provider: %s", fallback_order[idx + 1])
                continue
            break  # 所有 provider 都失败
        except Exception as e:
            logger.error("%s 未知异常: %s", provider_name, e)
            last_error = e
            if idx < len(fallback_order) - 1:
                continue
            break

    if report_text is None:
        logger.error("所有 provider 均失败，无法生成周报")
        error_msg = str(last_error or "未知错误")
        logger.error("最后一次错误: %s", error_msg)
        # 自动发送失败告警
        send_failure_alert(config, f"AI 接口调用失败: {error_msg}")
        if debug:
            logger.debug("LLM 调用异常堆栈:", exc_info=True)
        return None, ErrorCode.LLM_ERROR

    return report_text, None


def save_report_to_file(report_text: str, config: dict) -> Path:
    """保存周报到文件并打印，返回输出路径"""
    out_path = resolve_output_path(config)
    logger.info("=" * 60)
    logger.info("生成的周报内容：")
    logger.info("=" * 60)
    logger.info(report_text)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_text, encoding="utf-8")
    logger.info("周报已保存至: %s", out_path.absolute())
    return out_path


def handle_dingtalk_review(
    report_text: str, out_path: Path, config: dict, args: argparse.Namespace
) -> tuple[bool, Optional[int]]:
    """处理钉钉人工审核与推送

    Returns:
        (should_continue, error_code):
            should_continue=True 表示审核通过或无需审核，可继续后续步骤；
            should_continue=False 表示应终止流程（跳过或出错）。
            error_code 非 None 时表示出错应返回该码。
    """
    dt_cfg = config.get("dingtalk", {})
    need_confirm = dt_cfg.get("enabled", False) and not args.no_confirm
    decision = None  # 仅 need_confirm 为 True 时在下方赋值，此处显式初始化避免隐式依赖短路求值

    # 钉钉人工审核
    if need_confirm:
        try:
            decision, reason = wait_for_confirmation(report_text, out_path.name, config)
        except ValueError as e:
            logger.error("钉钉配置错误: %s", e)
            return False, ErrorCode.DINGTALK_ERROR
        except RuntimeError as e:
            logger.error("钉钉审核流程异常: %s", e)
            send_failure_alert(config, f"钉钉审核流程异常: {e}")
            if args.debug:
                logger.debug("钉钉审核流程异常堆栈:", exc_info=True)
            return False, ErrorCode.DINGTALK_ERROR
        logger.info("钉钉审核结果: %s（%s）", decision, reason)
        if decision != "confirm":
            logger.info("未获得审核确认，跳过钉钉推送与邮件发送。")
            return False, None  # 非错误，只是跳过后续

    # 发送钉钉周报（审核通过后推送给钉钉接收人）
    if dt_cfg.get("enabled") and (not need_confirm or decision == "confirm"):
        try:
            send_dingtalk_report(report_text, out_path.name, config)
        except ValueError as e:
            logger.error("钉钉配置错误: %s", e)
            return False, ErrorCode.DINGTALK_ERROR
        except RuntimeError as e:
            logger.error("钉钉周报发送失败: %s", e)
            send_failure_alert(config, f"钉钉周报发送失败: {e}")
            if args.debug:
                logger.debug("钉钉周报发送异常堆栈:", exc_info=True)
            return False, ErrorCode.DINGTALK_ERROR

    return True, None


def send_email_if_enabled(
    report_text: str,
    out_path: Path,
    config: dict,
    downloaded_excel_path: Optional[str],
    args: argparse.Namespace,
) -> Optional[int]:
    """根据配置和参数决定是否发送邮件

    Returns:
        错误码或 None（成功时返回 None）
    """
    if args.no_email:
        logger.info("已跳过邮件发送（--no-email）")
        return None
    if not config.get("email", {}).get("enabled"):
        return None

    try:
        send_report_email(report_text, out_path, config, downloaded_excel_path)
        return None
    except ValueError as e:
        logger.error("邮件配置错误: %s", e)
        return ErrorCode.EMAIL_ERROR
    except RuntimeError as e:
        logger.error("邮件发送失败: %s", e)
        send_failure_alert(config, f"邮件发送失败: {e}")
        if args.debug:
            logger.debug("邮件发送异常堆栈:", exc_info=True)
        return ErrorCode.EMAIL_ERROR


def main() -> int:
    args = parse_args()
    if not _acquire_lock():
        return ErrorCode.LOCK_FAILED
    try:
        return _run(args)
    except ValueError as e:
        logger.error("%s", e)
        if args.debug:
            logger.debug("配置异常堆栈:", exc_info=True)
        return ErrorCode.CONFIG_ERROR
    finally:
        _release_lock()


def _run(args: argparse.Namespace) -> int:
    config = load_config()

    # 1. 应用命令行参数覆盖配置（必须在日志初始化之前，否则日志文件名无法反映 --output 等参数）
    apply_args_to_config(args, config)

    # 1.5 启动前校验关键配置是否齐全，缺失时给出清晰提示
    missing = validate_required_config(config)
    if missing:
        raise ValueError(
            "启动配置校验失败，缺少以下关键配置：\n  - " + "\n  - ".join(missing)
        )

    # 2. 初始化日志系统
    log_path = init_run_logging(config, args.debug)

    # 3. 节假日检查
    skip_code = check_holiday_skip(args.force, log_path)
    if skip_code is not None:
        return skip_code

    # 4. CRM 下载
    downloaded_excel_path, error = download_crm_if_enabled(config, args)
    if error:
        return error

    # 5. 汇总 Excel 内容
    try:
        excel_text = aggregate_excel_content(config, downloaded_excel_path)
    except FileNotFoundError as e:
        logger.error("%s", e)
        return ErrorCode.CRM_ERROR

    if args.dry_run:
        logger.info("=" * 60)
        logger.info("Excel 汇总内容预览：")
        logger.info("=" * 60)
        logger.info(excel_text)
        return ErrorCode.SUCCESS

    # 6. 构建 Prompt 并调用 LLM
    prompt = build_prompt(excel_text, config)
    logger.info("Prompt 总字符数: %d", len(prompt))
    report_text, error = generate_report_via_llm(prompt, config, args.debug)
    if error:
        return error

    # 7. 保存周报
    out_path = save_report_to_file(report_text, config)

    # 8. 钉钉审核与推送
    should_continue, error = handle_dingtalk_review(report_text, out_path, config, args)
    if error:
        return error
    if not should_continue:
        return ErrorCode.SUCCESS

    # 9. 发送邮件
    error = send_email_if_enabled(report_text, out_path, config, downloaded_excel_path, args)
    if error:
        return error

    logger.info("全流程执行结束，运行日志: %s", log_path)
    return ErrorCode.SUCCESS


if __name__ == "__main__":
    sys.exit(main())
