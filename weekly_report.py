# -*- coding: utf-8 -*-
"""
AI 周报生成器 - 多 LLM Provider 支持（MiniMax / DeepSeek / OpenCode / Qwen）

读取指定文件夹中所有 Excel 文件第一列「项目/需求任务」内容，去重后交由 AI 总结整理，
返回一段可设置格式的周报文本，并可选通过腾讯企业邮箱发送。

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
import argparse
import sys
import traceback
import warnings

# 强制 stdout/stderr 使用 UTF-8 编码，避免 Windows PowerShell 中文乱码
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 抑制 openpyxl 读取部分 Excel 时产生的样式警告（不影响数据读取）
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

from config_manager import PROVIDER_PRESETS, load_config
from crm_downloader import download_workhour_excel
from email_sender import send_report_email
from excel_aggregator import aggregate_excel_content
from holiday_checker import should_skip_execution
from llm_client import FORMAT_TEMPLATES, build_prompt, call_llm_api
from output_resolver import resolve_output_path


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
    parser.add_argument("--force", action="store_true",
                        help="强制执行，跳过节假日检查（节假日也会执行）")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()

    # 0. 节假日检查：节假日/周末跳过执行（定时任务在周一运行，但周一可能是法定节假日）
    if not args.force:
        should_skip, reason = should_skip_execution()
        if should_skip:
            print(f"[INFO] {reason}")
            print("[INFO] 如需强制执行，请使用: python weekly_report.py --force")
            return 0

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

    # 1. CRM 接口下载工时 Excel（启用 CRM 时自动下载，跳过手动放置）
    crm_cfg = config.get("crm", {})
    downloaded_excel_path = None
    if crm_cfg.get("enabled") and not args.no_crm:
        try:
            print("\n" + "=" * 60)
            print("步骤 1/3: 从 CRM 接口下载工时 Excel")
            print("=" * 60)
            downloaded_excel_path = download_workhour_excel(
                config,
                start_date=args.crm_start,
                finish_date=args.crm_finish,
            )
        except ValueError as e:
            print(f"[ERROR] CRM 配置错误: {e}")
            return 1
        except RuntimeError as e:
            print(f"[ERROR] CRM 接口下载失败: {e}")
            if args.debug:
                traceback.print_exc()
            print("[INFO] 可使用 --no-crm 跳过下载，直接使用本地 Excel 文件")
            return 1
    elif args.no_crm:
        print("[INFO] 已跳过 CRM 接口下载（--no-crm），使用本地 Excel 文件")
    elif not crm_cfg.get("enabled"):
        print("[INFO] CRM 接口未启用，使用本地 excel_folder 下的 Excel 文件")

    # 2. 汇总 Excel 内容
    try:
        excel_text = aggregate_excel_content(config)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        return 1

    if args.dry_run:
        print("\n" + "=" * 60)
        print("Excel 汇总内容预览：")
        print("=" * 60)
        print(excel_text)
        return 0

    # 3. 构建 prompt
    prompt = build_prompt(excel_text, config)
    print(f"[INFO] Prompt 总字符数: {len(prompt)}")

    # 4. 调用 LLM API
    try:
        report_text = call_llm_api(prompt, config)
    except ValueError as e:
        # 配置类错误（如 api_key 缺失、provider 未知）
        print(f"[ERROR] 配置错误: {e}")
        return 2
    except RuntimeError as e:
        # 运行时错误（网络、鉴权、限流、服务端异常等）
        print(f"[ERROR] AI 接口调用失败: {e}")

        # 对部分错误给出切换 provider 的建议
        err_str = str(e)
        should_suggest_alt = any(
            kw in err_str for kw in ("401", "403", "429", "超时", "网络连接失败", "服务端异常")
        )
        if should_suggest_alt:
            providers = config.get("providers", {})
            current = config["provider"]
            alternatives = [
                p for p, cfg in providers.items()
                if p != current and cfg.get("api_key", "").strip()
            ]
            if alternatives:
                print(f"\n[提示] 可尝试切换到其他已配置 provider 重试：")
                for p in alternatives:
                    print(f"  python weekly_report.py --provider {p}")
        if args.debug:
            traceback.print_exc()
        return 2
    except Exception as e:
        print(f"[ERROR] 未知异常: {e}")
        traceback.print_exc()
        return 2

    # 5. 输出结果
    out_path = resolve_output_path(config)
    print("\n" + "=" * 60)
    print("生成的周报内容：")
    print("=" * 60)
    print(report_text)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_text, encoding="utf-8")
    print(f"\n[INFO] 周报已保存至: {out_path.absolute()}")

    # 6. 发送邮件（周报保存成功后）
    if not args.no_email and config.get("email", {}).get("enabled"):
        try:
            send_report_email(report_text, out_path, config, downloaded_excel_path)
        except ValueError as e:
            print(f"[ERROR] 邮件配置错误: {e}")
            return 3
        except RuntimeError as e:
            print(f"[ERROR] 邮件发送失败: {e}")
            if args.debug:
                traceback.print_exc()
            return 3
    elif args.no_email:
        print("[INFO] 已跳过邮件发送（--no-email）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
