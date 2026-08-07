# -*- coding: utf-8 -*-
"""CRM 工时 Excel 下载模块。

负责：
- 调用 CRM 接口 (exportWorkHourItems) 下载上一周的工时 Excel
- 自动计算上一周周一至周五的日期范围
- 支持手动指定日期范围（CLI 参数 --crm-start / --crm-finish）
- 下载前清理下载目录中的旧 Excel 文件，避免跨周混用
- 兼容二进制 Excel 响应与 JSON 响应（base64 / 错误信息）
- JWT token 失效时自动调用登录接口刷新 token 并写回 config.json
"""
import os
import json
import base64
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from retry_utils import retry_request


# ============ 日期范围计算 ============
def calc_last_week_workdays(today: Optional[datetime] = None) -> Tuple[str, str]:
    """计算上一周周一至周五的日期（YYYY-MM-DD 格式）。

    与 output_resolver.calc_last_week_range 保持一致：
        今天是周一(0) → 上周一 = today - 7天, 上周五 = today - 3天
        今天是周三(2) → 上周一 = today - 9天, 上周五 = today - 5天
    """
    today = today or datetime.now()
    weekday = today.weekday()  # 周一=0, 周日=6
    last_monday = today - timedelta(days=weekday + 7)
    last_friday = last_monday + timedelta(days=4)
    return last_monday.strftime("%Y-%m-%d"), last_friday.strftime("%Y-%m-%d")


def _fmt_date_no_leading_zero(dt: datetime) -> str:
    """格式化日期为 YYYY.M.D（去掉月份和日期的前导零），与周报文件名风格一致。"""
    return f"{dt.year}.{dt.month}.{dt.day}"


def calc_last_week_range_label(today: Optional[datetime] = None) -> str:
    """计算上一周周一至周五的日期范围标签（同年省略结束年份）。

    示例：2026.7.13-7.17
    用于 CRM 下载文件命名：{export_prefix}2026.7.13-7.17.xlsx（前缀见 crm.export_prefix 配置）
    """
    today = today or datetime.now()
    weekday = today.weekday()
    last_monday = today - timedelta(days=weekday + 7)
    last_friday = last_monday + timedelta(days=4)
    start_str = _fmt_date_no_leading_zero(last_monday)
    if last_monday.year == last_friday.year:
        end_str = f"{last_friday.month}.{last_friday.day}"
    else:
        end_str = _fmt_date_no_leading_zero(last_friday)
    return f"{start_str}-{end_str}"


# ============ Token 刷新 ============
def refresh_crm_token(config: Dict[str, Any]) -> str:
    """调用 CRM 登录接口刷新 JWT token，并写回 config.json。

    登录接口返回的 data 字段是加密的 token 字符串（非标准 JWT），
    直接作为 authorization 头中 Bearer: 后的值使用。

    Args:
        config: 全局配置字典（会原地更新 config["crm"]["token"]）

    Returns:
        新的 token 字符串

    Raises:
        RuntimeError: 登录接口调用失败或返回失败
        ValueError: 登录配置缺失
    """
    crm_cfg = config.get("crm", {})

    login_url = crm_cfg.get("login_url", "").strip()
    if not login_url:
        raise ValueError(
            "CRM 登录配置缺失: crm.login_url 未设置。"
            "请在 config.json 中配置登录接口地址以支持 token 自动刷新。"
        )

    username = os.getenv("CRM_USERNAME", "").strip() or crm_cfg.get("username", "").strip()
    if not username:
        raise ValueError(
            "CRM 登录配置缺失: crm.username 未设置。"
            "请在 config.json 中填入 CRM 登录账号（如 user001），"
            "或设置环境变量 CRM_USERNAME"
        )

    # 密码优先从环境变量读取，其次配置文件
    password = os.getenv("CRM_PASSWORD", "").strip()
    if not password:
        password = crm_cfg.get("password", "").strip()
    if not password:
        raise ValueError(
            "CRM 登录配置缺失: crm.password 未设置。"
            "请在 config.json 中填入加密后的密码，或设置环境变量 CRM_PASSWORD"
        )

    app_id = crm_cfg.get("app_id", "Chrome(149.0.0.0)")
    userid = crm_cfg.get("userid", "")

    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN",
        "content-type": "application/json",
        "requestbybrowser": "Y",
        "w3auth": "N",
    }
    if userid:
        headers["userid"] = userid

    body = {
        "name": username,
        "password": password,
        "appID": app_id,
        "passwordFlag": "1",
    }

    timeout = int(crm_cfg.get("timeout", 60))
    print(f"[INFO] CRM token 已失效，正在调用登录接口刷新: {login_url}")

    try:
        response = retry_request(
            requests.post,
            login_url,
            headers=headers,
            json=body,
            timeout=(10, timeout),
            max_retries=2,
            base_delay=1.0,
            backoff=2.0,
            func_name="CRM 登录接口",
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"CRM 登录接口请求异常: {e}")

    if response.status_code != 200:
        body_preview = response.text[:500] if response.text else "(空)"
        raise RuntimeError(
            f"CRM 登录接口请求失败 (HTTP {response.status_code})。响应: {body_preview}"
        )

    # 解析登录响应
    try:
        resp_json = response.json()
    except ValueError as e:
        raise RuntimeError(f"CRM 登录接口响应不是合法 JSON: {e}")

    if not resp_json.get("success", False) or resp_json.get("result") != "SUCCESS":
        msg = resp_json.get("message", "未知错误")
        raise RuntimeError(f"CRM 登录失败: {msg}")

    # JWT token 在响应头 authorization 字段中（格式 "Bearer:eyJ..."）
    # 注意：响应 body 的 data 字段是加密的会话凭证，不是 JWT，不能用作 Bearer token
    auth_header = response.headers.get("authorization", "")
    if not auth_header:
        raise RuntimeError(
            "CRM 登录接口返回成功但响应头中缺少 authorization 字段，无法获取新 token"
        )

    # 提取 "Bearer:" 后面的 JWT token 部分
    new_token = auth_header
    if new_token.startswith("Bearer:"):
        new_token = new_token[len("Bearer:"):]
    elif new_token.lower().startswith("bearer "):
        new_token = new_token[7:]
    new_token = new_token.strip()

    if not new_token or not new_token.startswith("eyJ"):
        # 安全：不输出 token 内容到日志，仅提示格式异常
        raise RuntimeError(
            "CRM 登录接口响应头 authorization 不是有效的 JWT token（应以 eyJ 开头）"
        )

    # 写回 config.json 持久化新 token
    _persist_token_to_config(config, new_token)
    print("[INFO] CRM token 刷新成功，已写回 config.json")
    return new_token


def _persist_token_to_config(config: Dict[str, Any], new_token: str) -> None:
    """将新 token 写回 config.json 文件（原地更新，保留其他配置和格式）。

    Args:
        config: 全局配置字典（会原地更新 config["crm"]["token"]）
        new_token: 新获取的 token 字符串
    """
    config.setdefault("crm", {})["token"] = new_token

    # 找到 config.json 文件路径
    config_path = Path(__file__).parent / "config.json"
    if not config_path.exists():
        print(f"[WARN] config.json 不存在于 {config_path}，token 仅更新到内存，未持久化")
        return

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            file_config = json.load(f)
        file_config.setdefault("crm", {})["token"] = new_token
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(file_config, f, ensure_ascii=False, indent=2)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[WARN] 写回 config.json 失败: {e}，token 仅更新到内存")


# ============ 旧文件清理 ============
def cleanup_download_dir(
    download_dir: Path,
    extensions: List[str],
    new_range_label: Optional[str] = None,
    export_prefix: str = "",
) -> int:
    """清理下载目录中日期范围重复的旧 Excel 文件，返回删除的文件数。

    仅删除与新下载文件日期范围相同的旧文件，避免覆盖其他周的历史 Excel。

    Args:
        download_dir: 下载目录
        extensions: Excel 扩展名列表
        new_range_label: 新下载文件的日期范围标签（如 "2026.7.13-7.17"）。
            若为 None 则回退到清空全部旧文件（兼容旧逻辑）。
        export_prefix: 下载文件名前缀（crm.export_prefix 配置），为空则不带前缀
    """
    if not download_dir.exists():
        download_dir.mkdir(parents=True, exist_ok=True)
        return 0

    # 根据文件名中的日期范围标签判断是否重复
    # 文件命名格式：{export_prefix}{range_label}.xlsx
    # 只删除日期范围相同的旧文件，保留其他周的历史文件
    target_keyword = f"{export_prefix}{new_range_label}" if new_range_label else None

    removed = 0
    for item in download_dir.iterdir():
        if not (item.is_file() and item.suffix.lower() in extensions):
            continue
        # 若提供了 new_range_label，仅删除日期范围相同的旧文件
        if target_keyword and target_keyword not in item.stem:
            continue
        try:
            item.unlink()
            removed += 1
        except OSError as e:
            print(f"  [WARN] 删除旧文件失败 {item.name}: {e}")
    return removed


# ============ 辅助函数（主下载流程拆分） ============
def _validate_crm_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """验证 CRM 配置完整性，返回 crm 配置字典。

    Args:
        config: 全局配置字典

    Returns:
        crm_cfg: CRM 配置字典

    Raises:
        ValueError: CRM 未启用或关键配置缺失
    """
    crm_cfg = config.get("crm", {})
    if not crm_cfg.get("enabled"):
        raise ValueError("CRM 下载未启用，请在 config.json 中设置 crm.enabled=true")

    url = crm_cfg.get("url", "").strip()
    if not url:
        raise ValueError("CRM 配置缺失: crm.url 未设置")

    return crm_cfg


def _resolve_crm_token(crm_cfg: Dict[str, Any]) -> str:
    """从配置或环境变量解析 CRM token。"""
    token = crm_cfg.get("token", "").strip()
    if not token:
        token = os.getenv("CRM_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "CRM 配置缺失: crm.token 未设置。"
            "请在 config.json 中填入 authorization Bearer 后面的 token 值，"
            "或设置环境变量 CRM_TOKEN"
        )
    return token


def _calc_date_range(
    start_date: Optional[str], finish_date: Optional[str]
) -> Tuple[str, str]:
    """计算下载日期范围，优先使用手动指定，否则自动计算上一周周一至周五。"""
    if start_date and finish_date:
        return start_date, finish_date
    auto_start, auto_finish = calc_last_week_workdays()
    return start_date or auto_start, finish_date or auto_finish


def _build_range_label(
    start_date: Optional[str], finish_date: Optional[str]
) -> str:
    """根据日期范围计算文件名标签（同年省略结束年份）。

    手动指定日期时解析后格式化，自动模式直接复用 calc_last_week_range_label。
    """
    if start_date and finish_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            finish_dt = datetime.strptime(finish_date, "%Y-%m-%d")
            start_str = _fmt_date_no_leading_zero(start_dt)
            if start_dt.year == finish_dt.year:
                end_str = f"{finish_dt.month}.{finish_dt.day}"
            else:
                end_str = _fmt_date_no_leading_zero(finish_dt)
            return f"{start_str}-{end_str}"
        except ValueError:
            return calc_last_week_range_label()
    return calc_last_week_range_label()


def _build_crm_headers(crm_cfg: Dict[str, Any], token: str) -> Dict[str, str]:
    """构建 CRM 请求头。"""
    h = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN",
        "authorization": f"Bearer:{token}",
        "content-type": "application/json",
        "requestbybrowser": "Y",
        "userid": crm_cfg.get("userid", ""),
    }
    tyinject = crm_cfg.get("tyinjectparams", "").strip()
    if tyinject:
        h["tyinjectparams"] = tyinject
    return h


def _build_crm_body(
    crm_cfg: Dict[str, Any], start_stamp: str, finish_stamp: str
) -> Dict[str, Any]:
    """构建 CRM 请求体。"""
    return {
        "startStamp": start_stamp,
        "finishStamp": finish_stamp,
        "pageQuery": False,
        "needHead": True,
        "unit": "h",
        "tab": "org",
        "orgOidList": crm_cfg.get("org_oid_list", []),
        "userOidList": crm_cfg.get("user_oid_list", []),
        "projectOidList": crm_cfg.get("project_oid_list", []),
        "sortList": None,
        "state": "",
    }


def _send_crm_request_with_retry(
    url: str,
    crm_cfg: Dict[str, Any],
    body: Dict[str, Any],
    token: str,
    config: Dict[str, Any],
) -> "requests.Response":
    """发送 CRM 请求，401 时自动刷新 token 并重试一次。

    Args:
        url: CRM 接口地址
        crm_cfg: CRM 配置字典
        body: 请求体
        token: 当前 token
        config: 全局配置（用于 token 刷新时传参）

    Returns:
        response: HTTP 响应对象

    Raises:
        RuntimeError: 网络异常或 token 刷新失败
    """
    timeout = int(crm_cfg.get("timeout", 60))

    for attempt in range(2):  # 最多 2 次：首次 + 刷新后重试 1 次
        headers = _build_crm_headers(crm_cfg, token)
        try:
            response = retry_request(
                requests.post,
                url,
                headers=headers,
                json=body,
                timeout=(10, timeout),
                max_retries=2,
                base_delay=1.0,
                backoff=2.0,
                func_name=f"CRM 下载 ({url})",
            )
        except requests.exceptions.ConnectTimeout:
            raise RuntimeError(
                f"CRM 接口连接超时（10秒未建立连接）。可能原因：网络异常、DNS 解析失败、"
                f"或 URL 不可达（当前: {url}）。"
            )
        except requests.exceptions.ReadTimeout:
            raise RuntimeError(
                f"CRM 接口读取超时（{timeout}秒未返回）。建议：增大 config.json 中 crm.timeout 值后重试。"
            )
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"CRM 接口网络连接失败: {e}\n可能原因：DNS 解析失败、无网络、防火墙拦截。"
            )
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"CRM 接口 HTTP 请求异常: {e}")

        # 401 鉴权失败：尝试刷新 token 后重试一次
        if response.status_code == 401 and attempt == 0:
            print("[WARN] CRM 鉴权失败 (HTTP 401)，token 已失效，尝试自动刷新...")
            try:
                token = refresh_crm_token(config)
            except (ValueError, RuntimeError) as e:
                raise RuntimeError(
                    f"CRM token 自动刷新失败: {e}\n"
                    "请手动更新 config.json 中 crm.token 后重试。"
                )
            print("[INFO] 使用新 token 重试 CRM 接口请求...")
            continue
        break  # 非 401 或已重试过，跳出循环

    return response


def _check_crm_response_status(response: "requests.Response", url: str) -> None:
    """检查 CRM 响应状态码，非 200 则抛出异常。"""
    status = response.status_code
    if status == 401:
        raise RuntimeError(
            "CRM 鉴权失败 (HTTP 401)：token 刷新后仍无效。"
            "请检查 crm.username / crm.password 配置是否正确，"
            "或手动登录 CRM 系统抓取最新 token 更新 config.json 中 crm.token 后重试。"
        )
    if status == 403:
        raise RuntimeError(
            "CRM 无访问权限 (HTTP 403)：当前账号无权调用该接口或查看该组织工时。"
        )
    if status == 404:
        raise RuntimeError(
            f"CRM 接口不存在 (HTTP 404)：请检查 crm.url 配置（当前: {url}）。"
        )
    if 500 <= status < 600:
        # 安全：不输出响应体到日志（可能含敏感信息），仅提示状态码
        raise RuntimeError(
            f"CRM 服务端异常 (HTTP {status})，请稍后重试。"
        )
    if status != 200:
        # 安全：不输出响应体到日志（可能含敏感信息），仅提示状态码
        raise RuntimeError(
            f"CRM 接口请求失败 (HTTP {status})。"
        )


def _resolve_download_dir(crm_cfg: Dict[str, Any]) -> Path:
    """解析下载目录路径（相对路径基于脚本所在目录），并自动创建。"""
    download_dir = Path(crm_cfg.get("download_dir", "excel_files"))
    if not download_dir.is_absolute():
        download_dir = Path(__file__).parent / download_dir
    download_dir.mkdir(parents=True, exist_ok=True)
    return download_dir


def _extract_excel_from_response(
    response: "requests.Response",
    range_label: str,
    start_stamp: str,
    finish_stamp: str,
    download_dir: Path,
    export_prefix: str = "",
) -> Path:
    """从 CRM 响应中提取 Excel 文件并保存到下载目录。

    支持两种响应格式：
    1. Excel 二进制流（Content-Type 含 spreadsheet/excel 等）
    2. JSON 响应（Base64 编码的 Excel 数据）

    Args:
        response: HTTP 响应对象
        range_label: 日期范围标签（用于文件命名）
        start_stamp: 起始日期（用于异常响应命名）
        finish_stamp: 结束日期（用于异常响应命名）
        download_dir: 下载目录
        export_prefix: 下载文件名前缀（crm.export_prefix 配置），为空则不带前缀

    Returns:
        save_path: 保存的 Excel 文件路径

    Raises:
        RuntimeError: 响应格式无法识别或数据缺失
    """
    filename = f"{export_prefix}{range_label}.xlsx"
    content_type = response.headers.get("Content-Type", "").lower()

    # 情况 1：直接返回 Excel 二进制
    excel_mime_keywords = ("spreadsheet", "excel", "octet-stream", "application/vnd")
    if any(kw in content_type for kw in excel_mime_keywords):
        save_path = download_dir / filename
        save_path.write_bytes(response.content)
        print(f"[INFO] Excel 下载成功 (二进制流): {save_path.name}")
        print(f"[INFO] 文件大小: {len(response.content) / 1024:.1f} KB")
        return save_path

    # 情况 2：返回 JSON
    try:
        data = response.json()
    except ValueError:
        # 非 JSON 且非 Excel，保存原始内容用于排查
        fallback_path = download_dir / f"crm_response_{start_stamp}_{finish_stamp}.txt"
        fallback_path.write_bytes(response.content)
        # 安全：不输出响应内容到日志（可能含敏感信息），仅提示已保存到文件
        raise RuntimeError(
            f"CRM 响应既非 Excel 二进制也非 JSON，已保存原始内容到 {fallback_path.name}。"
            f"Content-Type: {content_type}。请打开该文件排查。"
        )

    # 检查错误字段
    err = data.get("error") or data.get("errorMsg") or data.get("message")
    err_code = data.get("errorCode") or data.get("code")
    if err_code and str(err_code) not in ("0", "200", "success", "Success"):
        raise RuntimeError(
            f"CRM 接口返回错误: code={err_code}, msg={err}"
        )

    # 尝试从 JSON 中提取 Excel 数据
    # 常见字段名：data / fileData / file / content (base64)
    file_b64 = (
        data.get("data")
        or data.get("fileData")
        or data.get("file")
        or data.get("content")
        or ""
    )
    if isinstance(file_b64, dict):
        # 可能是 { filename: ..., content: ... } 结构
        filename = file_b64.get("filename") or file_b64.get("name")
        file_b64 = file_b64.get("content") or file_b64.get("data") or ""
        # 兜底：若没拿到 filename，用前面计算好的统一文件名
        if not filename:
            filename = f"{export_prefix}{range_label}.xlsx"

    if isinstance(file_b64, str) and file_b64:
        try:
            file_bytes = base64.b64decode(file_b64)
        except Exception as e:
            raise RuntimeError(
                f"CRM 返回 JSON 中包含 file 数据但 base64 解码失败: {e}"
            )
        save_path = download_dir / filename
        save_path.write_bytes(file_bytes)
        print(f"[INFO] Excel 下载成功 (JSON base64): {save_path.name}")
        print(f"[INFO] 文件大小: {len(file_bytes) / 1024:.1f} KB")
        return save_path

    # JSON 响应但未识别到 Excel 数据
    # 安全：不输出响应体到日志（可能含敏感信息）
    raise RuntimeError(
        "CRM 接口返回 JSON 但未识别到 Excel 文件数据。"
        "请检查 CRM 接口返回格式或账号权限。"
    )


# ============ 主下载函数 ============
def download_workhour_excel(
    config: Dict[str, Any],
    start_date: Optional[str] = None,
    finish_date: Optional[str] = None,
) -> Path:
    """从 CRM 接口下载工时 Excel 文件。

    Args:
        config: 全局配置字典
        start_date: 手动指定起始日期 (YYYY-MM-DD)，为 None 时自动计算上一周周一
        finish_date: 手动指定结束日期 (YYYY-MM-DD)，为 None 时自动计算上一周周五

    Returns:
        下载保存的 Excel 文件 Path

    Raises:
        RuntimeError: 接口调用失败、鉴权失败、响应解析失败等
        ValueError: CRM 配置缺失
    """
    # 1. 参数验证
    crm_cfg = _validate_crm_config(config)
    export_prefix = crm_cfg.get("export_prefix", "")

    # 2. 日期计算（统一计算一次，后续日志与命名共用，避免不一致）
    start_stamp, finish_stamp = _calc_date_range(start_date, finish_date)
    range_label = _build_range_label(start_date, finish_date)
    print(f"[INFO] CRM 工时下载日期范围: {start_stamp} ~ {finish_stamp} (文件命名标签: {range_label})")

    # 3. 请求构建
    token = _resolve_crm_token(crm_cfg)
    body = _build_crm_body(crm_cfg, start_stamp, finish_stamp)
    url = crm_cfg.get("url", "").strip()
    print(f"[INFO] 调用 CRM 接口下载工时 Excel: {url}")

    # 4. 网络请求（含鉴权重试）
    response = _send_crm_request_with_retry(url, crm_cfg, body, token, config)

    # 5. 状态码检查
    _check_crm_response_status(response, url)

    # 6. 下载目录准备与旧文件清理
    download_dir = _resolve_download_dir(crm_cfg)
    extensions = config.get("excel_extensions", [".xlsx", ".xls", ".xlsm"])
    removed = cleanup_download_dir(download_dir, extensions, range_label, export_prefix)
    if removed:
        print(f"[INFO] 已清理 {removed} 个日期范围重复的旧 Excel 文件（保留其他周历史文件）")

    # 7. 响应解析与文件保存
    return _extract_excel_from_response(
        response, range_label, start_stamp, finish_stamp, download_dir, export_prefix
    )