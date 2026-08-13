# -*- coding: utf-8 -*-
"""钉钉 userId 查询工具（三种方式）。

用途：钉钉机器人发送单聊消息需要接收人的 userId（staffId），
本工具提供三种获取方式，用于填入 config.json：
- dingtalk.approver_staff_ids（审核人）
- dingtalk.recipient_staff_ids（周报接收人）

使用方式：
    0. 列出部门结构（先找目标部门 ID，需开通通讯录读权限）：
       python dingtalk_userid.py --list-dept          # 根部门下的子部门
       python dingtalk_userid.py --list-dept 872611   # 指定部门下的子部门

    1. 一键查询部门内所有成员（默认根部门，需开通通讯录读权限）：
       python dingtalk_userid.py --dept          # 根部门（全员）
       python dingtalk_userid.py --dept 872611   # 指定部门 ID

    2. 按手机号查询（需开通「根据手机号查询用户」权限）：
       python dingtalk_userid.py --mobile 13800138000

    3. 消息触发（默认，无需权限）：
       python dingtalk_userid.py
       然后在钉钉中搜索机器人名称，进入单聊发送任意消息，打印发送人 userId。

    4. 群会话 ID 查询（--group，无需额外权限）：
       python dingtalk_userid.py --group
       然后在目标钉钉群中 @ 机器人发送任意消息，打印该群的 openConversationId
       （填入 config.json 的 crm_reminder.conversation_id / dingtalk.open_conversation_id）。
"""
import argparse
import asyncio
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config_manager import load_config
from dingtalk_confirmer import (
    get_credentials,
    get_userid_by_mobile,
    list_dept_members,
    list_dept_subs,
    run_stream_listener,
)
from logger import get_logger

logger = get_logger(__name__)

try:
    import dingtalk_stream
    from dingtalk_stream import AckMessage
    DINGTALK_STREAM_AVAILABLE = True
except ImportError:
    DINGTALK_STREAM_AVAILABLE = False


if DINGTALK_STREAM_AVAILABLE:
    class WhoamiHandler(dingtalk_stream.ChatbotHandler):

        def __init__(self, done_event: asyncio.Event, group_mode: bool = False):
            super().__init__()
            self.done_event = done_event
            self.group_mode = group_mode

        async def process(self, callback: dingtalk_stream.CallbackMessage):
            msg = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
            staff_id = getattr(msg, "sender_staff_id", "") or "(未获取到)"
            nick = getattr(msg, "sender_nick", "") or "(未知)"
            conv_id = getattr(msg, "conversation_id", "") or "(未获取到)"
            conv_type = str(getattr(msg, "conversation_type", "") or "")
            conv_title = getattr(msg, "conversation_title", "") or ""
            is_group = conv_type == "2"  # 1=单聊 2=群聊
            if self.group_mode and not is_group:
                # --group 模式下忽略单聊消息，仅打印提示继续等待群聊消息
                logger.info("[INFO] 收到单聊消息，已忽略。请在目标钉钉群中 @ 机器人。")
                return AckMessage.STATUS_OK, "OK"
            logger.info("")
            logger.info("=" * 60)
            if is_group:
                logger.info("收到群聊消息!（群名称: %s）", conv_title or "未知")
            else:
                logger.info("收到钉钉消息!")
            logger.info("  发送人昵称 : %s", nick)
            logger.info("  发送人 userId: %s", staff_id)
            logger.info("  会话类型   : %s", "群聊" if is_group else "单聊")
            logger.info("  conversationId: %s", conv_id)
            logger.info("=" * 60)
            if is_group:
                logger.info("请将上述 conversationId 填入 config.json 的")
                logger.info("crm_reminder.conversation_id（或 dingtalk.open_conversation_id）中。")
            else:
                logger.info("请将上述 userId 填入 config.json 的 dingtalk.approver_staff_ids")
                logger.info("或 dingtalk.recipient_staff_ids 中。")
            logger.info("")
            # 不再向钉钉回复任何内容，避免与周报审核流程的 Stream 连接抢占消息
            self.done_event.set()
            return AckMessage.STATUS_OK, "OK"
else:
    WhoamiHandler = None  # type: ignore[assignment,misc]


async def _run_stream(app_key: str, app_secret: str, group_mode: bool = False) -> None:
    done_event = asyncio.Event()

    handler = WhoamiHandler(done_event, group_mode=group_mode)
    credential = dingtalk_stream.Credential(app_key, app_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC, handler
    )
    listener_task = asyncio.create_task(run_stream_listener(client, done_event, 300))
    try:
        await asyncio.wait_for(done_event.wait(), timeout=300)
    except asyncio.TimeoutError:
        logger.info("[INFO] 等待 5 分钟未收到消息，已退出。请重新运行后尽快发送消息。")
    finally:
        try:
            if client.websocket is not None:
                await client.websocket.close()
        except Exception:
            pass
        listener_task.cancel()
        try:
            await listener_task
        except (asyncio.CancelledError, Exception):
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="钉钉 userId 查询工具")
    parser.add_argument("--mobile", help="按手机号查询成员 userId")
    parser.add_argument("--dept", nargs="?", const=1, type=int,
                        help="列出指定部门成员（默认根部门=1），如 --dept 872611")
    parser.add_argument("--list-dept", nargs="?", const=1, type=int,
                        help="列出指定部门的子部门（默认根部门=1），如 --list-dept 872611")
    parser.add_argument("--group", action="store_true",
                        help="获取群会话 ID：在目标钉钉群中 @ 机器人，打印该群 openConversationId")
    args = parser.parse_args()

    config = load_config()
    dt_cfg = config.get("dingtalk", {})
    try:
        app_key, app_secret = get_credentials(dt_cfg)
    except ValueError as e:
        logger.error("%s", e)
        return 1

    # 方式 0：列出子部门
    if args.list_dept is not None:
        try:
            subs = list_dept_subs(config, args.list_dept)
        except RuntimeError as e:
            logger.error("%s", e)
            return 2
        if not subs:
            logger.warning("部门 %s 下没有子部门", args.list_dept)
            return 0
        logger.info("=" * 60)
        logger.info("部门 %s 下的子部门（共 %d 个）：", args.list_dept, len(subs))
        logger.info("=" * 60)
        for d in subs:
            logger.info("  %s: %s", d["id"], d["name"])
        logger.info("")
        logger.info("请使用 --dept <部门ID> 查询对应部门成员。")
        return 0

    # 方式 2：按手机号查询
    if args.mobile:
        try:
            user_id = get_userid_by_mobile(config, args.mobile)
        except RuntimeError as e:
            logger.error("%s", e)
            return 2
        if not user_id:
            logger.warning("未查询到手机号 %s 对应的成员", args.mobile)
            return 2
        logger.info("=" * 60)
        logger.info("手机号 %s 对应的 userId: %s", args.mobile, user_id)
        logger.info("=" * 60)
        logger.info("请将此 userId 填入 config.json 的 dingtalk.approver_staff_ids")
        logger.info("或 dingtalk.recipient_staff_ids 中。")
        return 0

    # 方式 3：按部门列出成员
    if args.dept is not None:
        try:
            members = list_dept_members(config, args.dept)
        except RuntimeError as e:
            logger.error("%s", e)
            return 2
        if not members:
            logger.warning("部门 %s 下未查询到成员", args.dept)
            return 0
        logger.info("=" * 60)
        logger.info("部门 %s 共 %d 名成员：", args.dept, len(members))
        logger.info("=" * 60)
        for m in members:
            title = f"（{m['title']}）" if m["title"] else ""
            logger.info("  %s%s: %s", m["name"], title, m["userid"])
        logger.info("")
        logger.info("请将需要的 userId 填入 config.json 的钉钉配置中。")
        return 0

    # 方式 1（默认）：消息触发
    if not DINGTALK_STREAM_AVAILABLE:
        logger.error("未安装 dingtalk-stream，请先执行: pip install dingtalk-stream")
        return 1

    logger.info("=" * 60)
    if args.group:
        logger.info("钉钉群会话 ID 查询工具（群消息触发模式）")
        logger.info("=" * 60)
        logger.info("已启动 Stream 长连接，请执行以下操作：")
        logger.info("  1. 打开目标钉钉群（如项目群）")
        logger.info("  2. 在群内 @ 机器人并发送任意一条消息")
        logger.info("  3. 本程序将打印该群的 conversationId 并自动退出")
        logger.info("（5 分钟无消息自动退出；单聊消息将被忽略）")
        logger.info("")
    else:
        logger.info("钉钉 userId 查询工具（消息触发模式）")
        logger.info("=" * 60)
        logger.info("已启动 Stream 长连接，请执行以下操作：")
        logger.info("  1. 打开钉钉客户端")
        logger.info("  2. 顶部搜索您创建的机器人名称，进入单聊")
        logger.info("  3. 发送任意一条消息（如：我是谁）")
        logger.info("  4. 本程序将打印发送人 userId 并自动退出")
        logger.info("（5 分钟无消息自动退出）")
        logger.info("")

    asyncio.run(_run_stream(app_key, app_secret, group_mode=args.group))
    return 0


if __name__ == "__main__":
    sys.exit(main())
