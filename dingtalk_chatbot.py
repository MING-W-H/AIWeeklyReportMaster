# -*- coding: utf-8 -*-
"""钉钉 AI 问答机器人模块。

通过钉钉 Stream 长连接接收用户在钉钉中给机器人发送的消息（单聊 / 群聊 @ 机器人），
将用户消息连同预设的系统提示词（人设参数，如"你是公司的 AI 周报机器人…"）
一起发给大模型，再把模型回答回复给用户。

特点：
- 预设人设参数：config.json 中 chatbot.system_prompt 可自定义机器人的身份与行为
- 多轮对话：按会话（单聊按人、群聊按群）保留最近 N 轮上下文
- 权限控制：chatbot.allow_user_ids 白名单（留空则允许所有员工）
- 群聊仅在 @ 机器人时响应，单聊任意消息均响应
- 发送「清空 / 重置对话」等关键词可清除该会话历史

使用方式：
    python dingtalk_chatbot.py            # 启动机器人（常驻运行，Ctrl+C 退出）
    python dingtalk_chatbot.py --debug    # 打印详细日志

依赖：pip install dingtalk-stream（requirements.txt 已包含）
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import threading
from typing import Any, Dict, List

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config_manager import load_config
from dingtalk_confirmer import _get_credentials
from llm_client import call_llm_chat

try:
    import dingtalk_stream
    from dingtalk_stream import AckMessage

    DINGTALK_STREAM_AVAILABLE = True
except ImportError:
    DINGTALK_STREAM_AVAILABLE = False

# 回复消息的 Markdown 标题
_REPLY_TITLE = "AI 周报机器人"

# 默认系统提示词（人设参数）。config.json 的 chatbot.system_prompt 可覆盖。
DEFAULT_CHATBOT_SYSTEM_PROMPT = (
    "你是公司的 AI 周报机器人，"
    "由公司内部开发，服务于员工。"
    "你可以回答与周报系统、CRM 工时填写、公司日常事务等相关的各类问题。\n\n"
    "行为准则：\n"
    "1. 使用简体中文回答，语言专业、简洁、友好\n"
    "2. 涉及不确定或不清楚的信息时，如实说明，不要编造\n"
    "3. 涉及个人隐私或公司机密的信息，礼貌地表示不便回答\n"
    "4. 回答先给结论再给理由，不要使用 Markdown 表格"
)

# 清空对话上下文的关键词
DEFAULT_RESET_KEYWORDS = ["清空", "清空对话", "重置", "重置对话", "/clear"]


def _strip_at_prefix(text: str) -> str:
    """去掉群聊消息中 @机器人昵称 的前缀（部分客户端会把 @昵称 拼进文本）。"""
    return re.sub(r"^\s*@[^\s@]+(?:\s|$)", "", text).strip()


if DINGTALK_STREAM_AVAILABLE:

    class ChatbotLLMHandler(dingtalk_stream.AsyncChatbotHandler):
        """钉钉 AI 问答消息处理器（线程池执行，不阻塞 Stream 事件循环）。"""

        def __init__(self, config: Dict[str, Any]):
            super().__init__()
            self.config = config
            chatbot_cfg = config.get("chatbot", {})
            self.system_prompt = (
                (chatbot_cfg.get("system_prompt") or "").strip()
                or DEFAULT_CHATBOT_SYSTEM_PROMPT
            )
            self.allow_user_ids = {
                str(s).strip()
                for s in (chatbot_cfg.get("allow_user_ids") or [])
                if str(s).strip()
            }
            self.max_history_turns = max(1, int(chatbot_cfg.get("max_history_turns", 10)))
            self.max_reply_chars = int(chatbot_cfg.get("max_reply_chars", 8000))
            self.reset_keywords = [
                str(k).strip().lower()
                for k in (chatbot_cfg.get("reset_keywords") or DEFAULT_RESET_KEYWORDS)
            ]
            # 会话历史：会话标识 -> [{role, content}, ...]（role: user/assistant）
            self.histories: Dict[str, List[Dict[str, str]]] = {}
            self._lock = threading.Lock()

        def _trim_history(self, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
            """按轮次裁剪历史，仅保留最近 max_history_turns 轮（1 轮 = 1 条 user + 回答）。"""
            user_indices = [i for i, m in enumerate(history) if m["role"] == "user"]
            if len(user_indices) <= self.max_history_turns:
                return history
            drop_until = user_indices[len(user_indices) - self.max_history_turns]
            return history[drop_until:]

        def process(self, callback):
            try:
                msg = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
            except Exception:
                return AckMessage.STATUS_OK, "OK"

            # 仅处理文本消息
            text = ""
            if getattr(msg, "text", None) is not None:
                text = (getattr(msg.text, "content", "") or "").strip()
            if not text:
                return AckMessage.STATUS_OK, "OK"
            text = _strip_at_prefix(text)
            if not text:
                return AckMessage.STATUS_OK, "OK"

            sender_id = (getattr(msg, "sender_staff_id", "") or "").strip()
            sender_nick = getattr(msg, "sender_nick", "") or "(未知)"
            conv_type = str(getattr(msg, "conversation_type", "") or "")
            is_group = conv_type == "2"
            conv_id = (getattr(msg, "conversation_id", "") or "").strip()
            conv_title = getattr(msg, "conversation_title", "") or ""

            print(f"[INFO] 收到消息: {sender_nick} ({'群聊: ' + conv_title if is_group else '单聊'})")

            # 权限白名单：未授权用户拒绝服务
            if self.allow_user_ids and sender_id not in self.allow_user_ids:
                self.reply_markdown(
                    _REPLY_TITLE,
                    "抱歉，您暂无使用本机器人的权限。如有需要请联系管理员开通。",
                    msg,
                )
                return AckMessage.STATUS_OK, "OK"

            # 群聊：仅在 @ 机器人时响应
            if is_group and not (getattr(msg, "is_in_at_list", False)):
                return AckMessage.STATUS_OK, "OK"

            # 会话标识：单聊按发送人、群聊按群
            session_key = sender_id if not is_group else f"group:{conv_id}"

            # 清空对话关键词
            if text.lower() in self.reset_keywords:
                with self._lock:
                    self.histories.pop(session_key, None)
                self.reply_markdown(
                    _REPLY_TITLE,
                    "好的，本次对话的上下文已清空，我们可以开始新的话题。",
                    msg,
                )
                return AckMessage.STATUS_OK, "OK"

            # 追加用户消息并裁剪历史
            with self._lock:
                history = self._trim_history(self.histories.get(session_key, []))
                history.append({"role": "user", "content": text})

            # 调用大模型回答
            try:
                reply = call_llm_chat(history, self.config, system_prompt=self.system_prompt)
            except (ValueError, RuntimeError) as e:
                self.reply_markdown(
                    _REPLY_TITLE,
                    f"抱歉，AI 服务暂时不可用：{e}\n\n请稍后重试，或联系系统管理员。",
                    msg,
                )
                return AckMessage.STATUS_OK, "OK"
            except Exception:
                self.reply_markdown(
                    _REPLY_TITLE,
                    "抱歉，处理您的消息时出现异常，请稍后重试。",
                    msg,
                )
                return AckMessage.STATUS_OK, "OK"

            reply = (reply or "").strip()
            if not reply:
                self.reply_markdown(
                    _REPLY_TITLE,
                    "抱歉，AI 没有返回有效内容，请换一种问法试试。",
                    msg,
                )
                return AckMessage.STATUS_OK, "OK"

            # 保存模型回答到历史（形成多轮上下文）
            with self._lock:
                self.histories[session_key] = history + [{"role": "assistant", "content": reply}]

            # 回复（超长截断）
            display = (
                reply
                if len(reply) <= self.max_reply_chars
                else reply[: self.max_reply_chars] + "\n\n...(内容过长已截断)"
            )
            self.reply_markdown(_REPLY_TITLE, display, msg)
            print(f"[INFO] 已回复 {sender_nick}（{len(reply)} 字符）")
            return AckMessage.STATUS_OK, "OK"

else:
    ChatbotLLMHandler = None  # type: ignore[assignment,misc]


def run_chatbot(config: Dict[str, Any], debug: bool = False) -> int:
    """启动钉钉 AI 问答机器人（常驻运行，Ctrl+C 退出）。"""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if not DINGTALK_STREAM_AVAILABLE:
        print("[ERROR] 未安装 dingtalk-stream，请先执行: pip install dingtalk-stream")
        return 1

    chatbot_cfg = config.get("chatbot", {})
    if not chatbot_cfg.get("enabled"):
        print("[INFO] 聊天机器人未启用：config.json 中 chatbot.enabled = false，已退出。")
        print("[INFO] 如需启用，请将 chatbot.enabled 改为 true 后重新运行。")
        return 0

    dt_cfg = config.get("dingtalk", {})
    try:
        app_key, app_secret = _get_credentials(dt_cfg)
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 1

    provider_name = config.get("provider", "")
    model = config.get("providers", {}).get(provider_name, {}).get("model", "")
    allow_ids = [s for s in (chatbot_cfg.get("allow_user_ids") or []) if str(s).strip()]

    print("=" * 60)
    print("AI 周报机器人（大模型问答）")
    print("=" * 60)
    print(f"大模型: {provider_name} / {model}")
    print(f"允许用户: {'全部员工' if not allow_ids else ', '.join(allow_ids)}")
    print(f"对话上下文: 保留最近 {chatbot_cfg.get('max_history_turns', 10)} 轮")
    print("运行方式: Stream 长连接，常驻运行，按 Ctrl+C 退出")
    print("=" * 60)

    handler = ChatbotLLMHandler(config)
    credential = dingtalk_stream.Credential(app_key, app_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC, handler
    )

    try:
        client.start_forever()
    except KeyboardInterrupt:
        print("\n[INFO] 已退出聊天机器人服务。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="钉钉 AI 问答机器人（大模型接入）")
    parser.add_argument("--debug", action="store_true", help="打印详细日志")
    args = parser.parse_args()

    config = load_config()
    return run_chatbot(config, debug=args.debug)


if __name__ == "__main__":
    sys.exit(main())
