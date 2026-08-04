# -*- coding: utf-8 -*-
"""使用钉钉机器人向接收人发送周报通知（一次性通知脚本）。

发送对象：config.json 的 dingtalk.recipient_staff_ids。
通知模板：config.json 的 notification.templates.weekly_notice。
用法：
    python dingtalk_send_notice.py        # 发送通知（先预览，确认后发送）
    python dingtalk_send_notice.py --yes  # 跳过确认直接发送
    python dingtalk_send_notice.py --footer "本周周报已生成，请查收"  # 自定义尾部内容
"""
import argparse
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config_manager import load_config, render_notification
from dingtalk_confirmer import _get_credentials, _send_markdown_oto


def main() -> int:
    parser = argparse.ArgumentParser(description="使用钉钉机器人向接收人发送周报通知")
    parser.add_argument("--yes", action="store_true", help="跳过预览确认直接发送")
    parser.add_argument("--footer", default="", help="通知尾部附加内容（可选）")
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

    # 从配置模板渲染通知文本
    try:
        notice_title, notice_text = render_notification(config, "weekly_notice", footer=args.footer)
    except KeyError as e:
        print(f"[ERROR] {e}")
        return 1

    print("=" * 60)
    print("即将发送以下通知：")
    print(f"  标题: {notice_title}")
    print(f"  接收人 ({len(recipient_ids)} 人): {recipient_ids}")
    print("-" * 60)
    print(notice_text)
    print("=" * 60)
    if not args.yes:
        answer = input("确认发送？(y/N): ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消，未发送。")
            return 0

    try:
        _send_markdown_oto(app_key, app_secret, recipient_ids, notice_title, notice_text)
    except RuntimeError as e:
        print(f"[ERROR] 发送失败: {e}")
        return 2
    print(f"[OK] 周报通知已发送给 {len(recipient_ids)} 位接收人")
    return 0


if __name__ == "__main__":
    sys.exit(main())
