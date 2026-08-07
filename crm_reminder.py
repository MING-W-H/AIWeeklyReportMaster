# -*- coding: utf-8 -*-
"""CRM 填写提醒脚本（钉钉群消息）。

每周五下午 15:00 向指定钉钉群发送「CRM 工时填写」提醒，并 @ 部分成员，
提醒他们记得填写 CRM 系统。

使用方式：
    python crm_reminder.py                  # 检查今天是否为发送日（默认周五）后发送（先预览确认）
    python crm_reminder.py --yes            # 跳过预览确认直接发送（定时任务使用）
    python crm_reminder.py --force          # 强制发送，跳过「周五/节假日」前置检查
    python crm_reminder.py --yes --force    # 手动补发（定时任务漏发时）

配置（config.json）：
    crm_reminder.enabled: true                          # 启用 CRM 填写提醒
    crm_reminder.send_weekday: 4                        # 每周几发送：0=周一 ... 6=周日（默认 4=周五）
    crm_reminder.skip_holiday: true                     # 法定节假日/周末自动跳过（复用 holiday_checker）
    crm_reminder.conversation_id: "cidXXX=="            # 目标钉钉群 openConversationId
                                                        #   （留空回退 dingtalk.open_conversation_id）
    crm_reminder.remind_user_ids: ["user001", ...]      # 需要 @ 的成员 userId
                                                        #   （运行 dingtalk_userid.py --dept 获取）
    notification.templates.crm_reminder:                # 提醒内容模板（支持 {names} 占位符 = @名单）

权限要求：
- 企业内机器人发送消息权限（qyapi_robot_sendmsg，与周报推送一致）
- 成员信息读权限（可选，用于把 userId 解析为姓名显示在 @ 文本中）

定时任务注册（管理员 PowerShell）：
    .\register_crm_reminder.ps1      # 每周五 15:00 执行 run_crm_reminder.bat

凭证：环境变量 DINGTALK_APP_KEY / DINGTALK_APP_SECRET > config.json dingtalk.app_key / app_secret。
"""
import argparse
import sys
from datetime import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import requests

from config_manager import load_config, render_notification
from dingtalk_confirmer import (
    _get_credentials,
    _get_oapi_access_token,
    _send_markdown_group,
)
from holiday_checker import is_holiday
from retry_utils import retry_request

_GET_USER_URL = "https://oapi.dingtalk.com/topapi/v2/user/get"

_WEEKDAY_CN = "一二三四五六日"


def _resolve_names(app_key: str, app_secret: str, user_ids) -> dict:
    """尽力把 userId 解析为姓名（权限不足时回退为 userId 本身）。"""
    if not user_ids:
        return {}
    token = _get_oapi_access_token(app_key, app_secret)
    names = {}
    for uid in user_ids:
        try:
            resp = retry_request(
                requests.post,
                _GET_USER_URL,
                params={"access_token": token},
                json={"userid": uid},
                timeout=15,
                max_retries=1,
                base_delay=1.0,
                backoff=2.0,
                func_name="钉钉用户信息查询",
            )
            data = resp.json()
            if data.get("errcode") == 0:
                names[uid] = (data.get("result") or {}).get("name", "") or ""
        except Exception:
            pass
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description="向钉钉群发送 CRM 填写提醒（默认每周五 15:00）")
    parser.add_argument("--yes", action="store_true", help="跳过预览确认直接发送")
    parser.add_argument("--force", action="store_true", help="强制发送，跳过周五/节假日检查")
    args = parser.parse_args()

    config = load_config()
    dt_cfg = config.get("dingtalk", {})
    rm_cfg = config.get("crm_reminder", {})

    if not dt_cfg.get("enabled"):
        print("[ERROR] dingtalk.enabled 为 false，请先在 config.json 中启用钉钉")
        return 1
    if not rm_cfg.get("enabled"):
        print("[ERROR] crm_reminder.enabled 为 false，请先在 config.json 中启用 CRM 填写提醒")
        return 1

    try:
        app_key, app_secret = _get_credentials(dt_cfg)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1

    # ---- 发送日期前置检查（--force 跳过） ----
    today = datetime.now()
    weekday = int(rm_cfg.get("send_weekday", 4))
    if not args.force and today.weekday() != weekday:
        print(f"[SKIP] 今天是星期{_WEEKDAY_CN[today.weekday()]}，非发送日"
              f"（配置为星期{_WEEKDAY_CN[weekday]}），不发送")
        return 0
    if not args.force and rm_cfg.get("skip_holiday", True) and is_holiday(today.date()):
        print(f"[SKIP] 今天（{today:%Y-%m-%d}）为节假日，不发送")
        return 0

    # ---- 目标群 ----
    conversation_id = str(
        rm_cfg.get("conversation_id") or dt_cfg.get("open_conversation_id") or ""
    ).strip()
    if not conversation_id:
        print("[ERROR] 未配置目标钉钉群：请在 config.json 的 crm_reminder.conversation_id"
              "（或 dingtalk.open_conversation_id）中填入群 openConversationId")
        return 1

    # ---- @ 名单 ----
    remind_ids = [str(s).strip() for s in (rm_cfg.get("remind_user_ids") or []) if str(s).strip()]
    names_map = _resolve_names(app_key, app_secret, remind_ids)
    at_text = " ".join(f"@{names_map.get(uid) or uid}" for uid in remind_ids)

    # ---- 渲染消息 ----
    try:
        title, text = render_notification(
            config, "crm_reminder", names=at_text, date=f"{today:%Y-%m-%d}"
        )
    except KeyError as e:
        print(f"[ERROR] {e}")
        return 1

    print("=" * 60)
    print("即将发送以下 CRM 填写提醒：")
    print(f"  标题: {title}")
    print(f"  目标群: {conversation_id}")
    print(f"  @成员 ({len(remind_ids)} 人): {remind_ids}")
    print("-" * 60)
    print(text)
    print("=" * 60)
    if not args.yes:
        answer = input("确认发送？(y/N): ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消，未发送。")
            return 0

    try:
        _send_markdown_group(app_key, app_secret, conversation_id, title, text,
                             at_user_ids=remind_ids)
    except RuntimeError as e:
        print(f"[ERROR] 发送失败: {e}")
        return 2
    print(f"[OK] CRM 填写提醒已发送到钉钉群（@ {len(remind_ids)} 人）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
