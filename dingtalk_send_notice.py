# -*- coding: utf-8 -*-
"""使用钉钉机器人向接收人发送周报通知（一次性通知脚本）。

发送对象：config.json 的 dingtalk.recipient_staff_ids。
用法：
    python dingtalk_send_notice.py        # 发送默认通知（先预览，确认后发送）
    python dingtalk_send_notice.py --yes  # 跳过确认直接发送
"""
import argparse
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config_manager import load_config
from dingtalk_confirmer import _get_credentials, _send_markdown_oto

NOTICE_TITLE = "周报通知"
NOTICE_TEXT = """各位领导好：

📌 重要通知：自本周起，周报将统一通过本钉钉机器人发送，后续请留意机器人消息提醒，及时查收周报内容。

如需查看周报详情或对内容有疑问，可通过以下方式联系我：
📱 钉钉：本机器人
📧 邮箱：jackeyming.wang@qq.com
📞 电话：13042762330"""


def main() -> int:
    parser = argparse.ArgumentParser(description="使用钉钉机器人向接收人发送周报通知")
    parser.add_argument("--yes", action="store_true", help="跳过预览确认直接发送")
    args = parser.parse_args()

    config = load_config()
    dt_cfg = config.get("dingtalk", {})
    if not dt_cfg.get("enabled"):
        print("[ERROR] dingtalk.enabled 为 false，请先在 config.json 中启用钉钉")
        return 1

    try:
        app_key, app_secret = _get_credentials(dt_cfg)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1

    recipient_ids = [s.strip() for s in (dt_cfg.get("recipient_staff_ids") or []) if str(s).strip()]
    if not recipient_ids:
        print("[ERROR] dingtalk.recipient_staff_ids 未配置接收人")
        return 1

    print("=" * 60)
    print("即将发送以下通知：")
    print(f"  标题: {NOTICE_TITLE}")
    print(f"  接收人 ({len(recipient_ids)} 人): {recipient_ids}")
    print("-" * 60)
    print(NOTICE_TEXT)
    print("=" * 60)
    if not args.yes:
        answer = input("确认发送？(y/N): ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消，未发送。")
            return 0

    try:
        _send_markdown_oto(app_key, app_secret, recipient_ids, NOTICE_TITLE, NOTICE_TEXT)
    except RuntimeError as e:
        print(f"[ERROR] 发送失败: {e}")
        return 2
    print(f"[OK] 周报通知已发送给 {len(recipient_ids)} 位接收人")
    return 0


if __name__ == "__main__":
    sys.exit(main())
