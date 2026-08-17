# -*- coding: utf-8 -*-
"""钉钉人工审核模块。

流程：
1. AI 生成周报后，调用 wait_for_confirmation() 向审核人（approver_staff_ids）
   的单聊推送一条「待审核周报预览」（Markdown）
2. 通过钉钉 Stream 长连接监听审核人回复：
   - 回复确认关键词（默认「发送」）→ 审核通过
   - 回复取消关键词（默认「取消」）→ 提示审核人说明存在哪些问题，等待其反馈
   - 收到反馈后调用 regenerate_fn 将反馈重新发送给大模型重新生成周报，
     生成完成后再次推送审核（可多轮迭代），直至确认发送、放弃或超时
   - 超时（默认 30 分钟）无回复 → 自动放弃
3. 审核通过后，调用 send_dingtalk_report() 将周报推送给钉钉接收人
   （recipient_staff_ids 单聊 和/或 open_conversation_id 群聊）

凭证优先级：环境变量 DINGTALK_APP_KEY / DINGTALK_APP_SECRET > config.json dingtalk.app_key / app_secret

依赖：pip install dingtalk-stream
"""
import asyncio
import json
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import requests
import websockets

from logger import get_logger
from retry_utils import retry_request

logger = get_logger(__name__)

try:
    import dingtalk_stream
    from dingtalk_stream import AckMessage

    DINGTALK_STREAM_AVAILABLE = True
except ImportError:
    DINGTALK_STREAM_AVAILABLE = False

# 钉钉开放平台 API
_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
_OAPI_TOKEN_URL = "https://oapi.dingtalk.com/gettoken"
_SEND_OTO_URL = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
_SEND_GROUP_URL = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
_GET_USER_BY_MOBILE_URL = "https://oapi.dingtalk.com/topapi/v2/user/getbymobile"
_LIST_DEPT_URL = "https://oapi.dingtalk.com/topapi/v2/department/listsub"
_LIST_USER_URL = "https://oapi.dingtalk.com/topapi/v2/user/list"

DEFAULT_CONFIRM_KEYWORDS = ["发送", "send", "确认", "ok"]
DEFAULT_CANCEL_KEYWORDS = ["取消", "cancel", "放弃", "不发送"]


def get_credentials(dt_cfg: Dict[str, Any]) -> Tuple[str, str]:
    """读取钉钉应用凭证：环境变量 > config.json。"""
    app_key = (os.getenv("DINGTALK_APP_KEY") or dt_cfg.get("app_key", "")).strip()
    app_secret = (os.getenv("DINGTALK_APP_SECRET") or dt_cfg.get("app_secret", "")).strip()
    if not app_key or not app_secret:
        raise ValueError(
            "钉钉凭证未配置：请在 .env 中设置 DINGTALK_APP_KEY / DINGTALK_APP_SECRET，"
            "或在 config.json 的 dingtalk.app_key / app_secret 中填入"
        )
    return app_key, app_secret


def _get_access_token(app_key: str, app_secret: str) -> str:
    """获取钉钉 API access_token。"""
    try:
        resp = retry_request(
            requests.post,
            _TOKEN_URL,
            json={"appKey": app_key, "appSecret": app_secret},
            timeout=15,
            max_retries=2,
            base_delay=1.0,
            backoff=2.0,
            func_name="钉钉 access_token 获取",
        )
    except requests.RequestException as e:
        raise RuntimeError(f"获取钉钉 access_token 网络异常: {e}")
    if resp.status_code != 200:
        raise RuntimeError(f"获取钉钉 access_token 失败: HTTP {resp.status_code} {resp.text}")
    data = resp.json()
    token = data.get("accessToken", "")
    if not token:
        raise RuntimeError(f"获取钉钉 access_token 失败: {data}")
    return token


def get_oapi_access_token(app_key: str, app_secret: str) -> str:
    """获取旧版 oapi access_token（通讯录接口使用该端点）。"""
    try:
        resp = retry_request(
            requests.get,
            _OAPI_TOKEN_URL,
            params={"appkey": app_key, "appsecret": app_secret},
            timeout=15,
            max_retries=2,
            base_delay=1.0,
            backoff=2.0,
            func_name="钉钉 oapi access_token 获取",
        )
    except requests.RequestException as e:
        raise RuntimeError(f"获取钉钉 oapi access_token 网络异常: {e}")
    data = resp.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"获取钉钉 oapi access_token 失败: {data.get('errmsg', data)}")
    return data.get("access_token", "")


def get_userid_by_mobile(config: Dict[str, Any], mobile: str) -> str:
    """按手机号查询成员 userId。需已开通「成员信息读权限」。"""
    dt_cfg = config.get("dingtalk", {})
    app_key, app_secret = get_credentials(dt_cfg)
    token = get_oapi_access_token(app_key, app_secret)
    try:
        resp = retry_request(
            requests.post,
            _GET_USER_BY_MOBILE_URL,
            params={"access_token": token},
            json={"mobile": mobile},
            timeout=15,
            max_retries=2,
            base_delay=1.0,
            backoff=2.0,
            func_name="钉钉手机号查询",
        )
    except requests.RequestException as e:
        raise RuntimeError(f"钉钉手机号查询网络异常: {e}")
    data = resp.json()
    if data.get("errcode") != 0:
        errmsg = data.get("errmsg", "未知错误")
        if "60011" in str(data.get("errcode")) or "无权" in errmsg:
            raise RuntimeError(
                f"权限不足: {errmsg}。请在钉钉开发者后台「权限管理」中申请"
                f"「成员信息读权限 / 根据手机号查询用户」后重试"
            )
        raise RuntimeError(f"钉钉手机号查询失败: {errmsg}")
    return data.get("result", {}).get("userid", "")


def list_dept_subs(config: Dict[str, Any], dept_id: int = 1) -> List[Dict[str, str]]:
    """列出指定部门下的子部门（id + 名称）。需已开通通讯录读权限。"""
    dt_cfg = config.get("dingtalk", {})
    app_key, app_secret = get_credentials(dt_cfg)
    token = get_oapi_access_token(app_key, app_secret)

    try:
        resp = retry_request(
            requests.post,
            _LIST_DEPT_URL,
            params={"access_token": token},
            json={"dept_id": dept_id},
            timeout=15,
            max_retries=2,
            base_delay=1.0,
            backoff=2.0,
            func_name="钉钉部门列表查询",
        )
    except requests.RequestException as e:
        raise RuntimeError(f"钉钉部门列表查询网络异常: {e}")
    data = resp.json()
    if data.get("errcode") != 0:
        errmsg = data.get("errmsg", "未知错误")
        if "无权" in errmsg:
            raise RuntimeError(
                f"权限不足: {errmsg}。请在钉钉开发者后台「权限管理」中申请"
                f"「通讯录部门信息读权限」后重试"
            )
        raise RuntimeError(f"钉钉部门列表查询失败: {errmsg}")
    return [
        {"id": d.get("dept_id", ""), "name": d.get("name", "")}
        for d in data.get("result", [])
    ]


def list_dept_members(config: Dict[str, Any], dept_id: int = 1) -> List[Dict[str, str]]:
    """列出指定部门下的成员（姓名 + userId）。需已开通通讯录读权限。"""
    dt_cfg = config.get("dingtalk", {})
    app_key, app_secret = get_credentials(dt_cfg)
    token = get_oapi_access_token(app_key, app_secret)

    members: List[Dict[str, str]] = []
    cursor = 0
    while True:
        try:
            resp = retry_request(
                requests.post,
                _LIST_USER_URL,
                params={"access_token": token},
                json={"dept_id": dept_id, "cursor": cursor, "size": 100},
                timeout=15,
                max_retries=2,
                base_delay=1.0,
                backoff=2.0,
                func_name="钉钉成员列表查询",
            )
        except requests.RequestException as e:
            raise RuntimeError(f"钉钉成员列表查询网络异常: {e}")
        data = resp.json()
        if data.get("errcode") != 0:
            errmsg = data.get("errmsg", "未知错误")
            if "无权" in errmsg:
                raise RuntimeError(
                    f"权限不足: {errmsg}。请在钉钉开发者后台「权限管理」中申请"
                    f"「通讯录部门信息读权限」和「成员信息读权限」后重试"
                )
            raise RuntimeError(f"钉钉成员列表查询失败: {errmsg}")
        result = data.get("result", {})
        for user in result.get("list", []):
            members.append({
                "name": user.get("name", ""),
                "userid": user.get("userid", ""),
                "title": user.get("title", ""),
            })
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor", 0)
    return members


def send_markdown_oto(app_key: str, app_secret: str, user_ids: List[str],
                      title: str, text: str) -> None:
    """通过机器人批量发送单聊 Markdown 消息。robotCode 即应用 Client ID。"""
    if not user_ids:
        return
    token = _get_access_token(app_key, app_secret)
    payload = {
        "robotCode": app_key,
        "userIds": list(user_ids),
        "msgKey": "sampleMarkdown",
        "msgParam": json.dumps({"title": title, "text": text}, ensure_ascii=False),
    }
    try:
        resp = retry_request(
            requests.post,
            _SEND_OTO_URL,
            headers={"x-acs-dingtalk-access-token": token},
            json=payload,
            timeout=30,
            max_retries=2,
            base_delay=1.0,
            backoff=2.0,
            func_name="钉钉单聊消息发送",
        )
    except requests.RequestException as e:
        raise RuntimeError(f"钉钉单聊消息发送网络异常: {e}")
    if resp.status_code != 200:
        raise RuntimeError(f"钉钉单聊消息发送失败: HTTP {resp.status_code} {resp.text}")


def send_markdown_group(app_key: str, app_secret: str, conversation_id: str,
                        title: str, text: str,
                        at_user_ids: Optional[List[str]] = None) -> None:
    """通过机器人发送群聊 Markdown 消息。

    Args:
        at_user_ids: 可选，需要 @ 提醒的成员 userId 列表（为空则不 @）
    """
    if not conversation_id:
        return
    token = _get_access_token(app_key, app_secret)
    msg_param: Dict[str, Any] = {"title": title, "text": text}
    if at_user_ids:
        msg_param["at"] = {"atUserIds": list(at_user_ids), "isAtAll": False}
    payload = {
        "robotCode": app_key,
        "openConversationId": conversation_id,
        "msgKey": "sampleMarkdown",
        "msgParam": json.dumps(msg_param, ensure_ascii=False),
    }
    try:
        resp = retry_request(
            requests.post,
            _SEND_GROUP_URL,
            headers={"x-acs-dingtalk-access-token": token},
            json=payload,
            timeout=30,
            max_retries=2,
            base_delay=1.0,
            backoff=2.0,
            func_name="钉钉群聊消息发送",
        )
    except requests.RequestException as e:
        raise RuntimeError(f"钉钉群聊消息发送网络异常: {e}")
    if resp.status_code != 200:
        raise RuntimeError(f"钉钉群聊消息发送失败: HTTP {resp.status_code} {resp.text}")


def _truncate(text: str, max_chars: int) -> str:
    """超长截断（钉钉 Markdown 消息有大小限制）。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n...(内容过长已截断，完整版请查看周报文件)"


def _build_preview(report_text: str, report_name: str,
                   confirm_kws: List[str], cancel_kws: List[str],
                   timeout_minutes: float, max_chars: int,
                   round_num: int = 1) -> str:
    """构建发送给审核人的待审核预览消息。

    Args:
        round_num: 审核轮次（第 1 版为初次生成，>1 为按反馈重新生成的版本）
    """
    body = _truncate(report_text, max_chars)
    header = "## 周报待审核"
    if round_num > 1:
        header += f"（第 {round_num} 版，已按您的反馈重新生成）"
    return "\n".join([
        header,
        f"**报告文件**: {report_name}",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
        body,
        "",
        "---",
        "",
        f"审核完成后请回复 **{'/'.join(confirm_kws)}** 确认发送（钉钉+邮件），",
        f"如需修改请**直接回复具体问题**（我会根据反馈重新生成后再次请您审核），",
        f"或回复 **{'/'.join(cancel_kws)}** 取消发送。",
        f"超过 {timeout_minutes:g} 分钟未回复将自动放弃。",
    ])


if DINGTALK_STREAM_AVAILABLE:

    class _ApprovalHandler(dingtalk_stream.ChatbotHandler):
        """监听审核人回复的 Stream 消息处理器。

        支持两阶段交互（enable_feedback=True 时）：
        - 阶段 1（等待决定）：回复确认关键词 → confirm；回复取消关键词 → 进入阶段 2；
          其他 → 提示未识别指令
        - 阶段 2（等待反馈）：回复取消关键词 → cancel（最终放弃）；其他文本 →
          视为问题反馈，设置 decision="regenerate" 并携带 feedback 供重新生成
        """

        def __init__(self, done_event: asyncio.Event, result: Dict[str, Any],
                     confirm_kws: List[str], cancel_kws: List[str],
                     approver_ids: List[str], enable_feedback: bool = False):
            super().__init__()
            self.done_event = done_event
            self.result = result
            self.confirm_kws = [k.strip().lower() for k in confirm_kws]
            self.cancel_kws = [k.strip().lower() for k in cancel_kws]
            self.approver_ids = set(approver_ids)
            self.enable_feedback = enable_feedback

        async def process(self, callback: "dingtalk_stream.CallbackMessage"):
            try:
                msg = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
            except Exception:
                return AckMessage.STATUS_OK, "OK"

            # 已有审核结论后忽略后续消息
            if self.result.get("decision") is not None:
                return AckMessage.STATUS_OK, "OK"

            sender_id = (getattr(msg, "sender_staff_id", "") or "").strip()
            # 仅接受配置的审核人回复；未配置时接受任何人
            if self.approver_ids and sender_id not in self.approver_ids:
                self.reply_text("您不是本流程的审核人，回复已忽略。", msg)
                return AckMessage.STATUS_OK, "OK"

            text = ""
            raw_text = ""
            if getattr(msg, "text", None) is not None:
                raw_text = (getattr(msg.text, "content", "") or "").strip()
                text = raw_text.lower()

            # 阶段 2：等待审核人提供问题反馈（已取消，需重新生成）
            if self.enable_feedback and self.result.get("phase") == "awaiting_feedback":
                if text in self.cancel_kws:
                    self.result["decision"] = "cancel"
                    self.result["sender"] = sender_id
                    self.reply_text("已取消本次周报发送。", msg)
                    self.done_event.set()
                else:
                    self.result["decision"] = "regenerate"
                    self.result["sender"] = sender_id
                    self.result["feedback"] = raw_text
                    self.reply_text(
                        "已收到您的反馈，正在重新生成周报，完成后将再次发送给您审核。", msg,
                    )
                    self.done_event.set()
                return AckMessage.STATUS_OK, "OK"

            # 阶段 1：等待确认/取消
            if text in self.confirm_kws:
                self.result["decision"] = "confirm"
                self.result["sender"] = sender_id
                self.reply_text("已确认，正在发送周报（钉钉 + 邮件）...", msg)
                self.done_event.set()
            elif text in self.cancel_kws:
                if self.enable_feedback:
                    self.result["phase"] = "awaiting_feedback"
                    self.reply_text(
                        "已收到取消。请问您认为本次周报有哪些地方存在问题？"
                        "请直接回复具体反馈（如数据遗漏、格式问题、表述不准确等），"
                        "我会根据您的反馈重新生成后再次发送给您审核。\n"
                        f"若确认无需修改、直接放弃发送，请回复「{'/'.join(self.cancel_kws)}」。",
                        msg,
                    )
                else:
                    self.result["decision"] = "cancel"
                    self.result["sender"] = sender_id
                    self.reply_text("已取消本次周报发送。", msg)
                    self.done_event.set()
            elif self.enable_feedback and raw_text:
                # 直接以非关键词文本提出修改意见 → 视为问题反馈并触发重新生成
                self.result["decision"] = "regenerate"
                self.result["sender"] = sender_id
                self.result["feedback"] = raw_text
                self.reply_text(
                    "已收到您的反馈，正在重新生成周报，完成后将再次发送给您审核。", msg,
                )
                self.done_event.set()
            else:
                confirm_hint = "/".join(self.confirm_kws)
                cancel_hint = "/".join(self.cancel_kws)
                self.reply_text(
                    f"未识别的指令。请回复「{confirm_hint}」确认发送，"
                    f"或回复「{cancel_hint}」放弃发送。", msg,
                )
            return AckMessage.STATUS_OK, "OK"


async def run_stream_listener(client, done_event: asyncio.Event,
                              timeout_sec: float) -> None:
    """自实现的 Stream 监听循环。

    与 SDK 自带的 client.start() 不同：该循环支持通过 done_event 优雅退出。
    SDK 的 start() 会捕获 CancelledError 后无限重连，无法停止，
    这正是之前 wait_for_confirmation() 在审核通过后永久挂起的原因。
    """
    start_time = time.time()

    while True:
        # 超时检查
        if time.time() - start_time > timeout_sec:
            return
        if done_event.is_set():
            return

        try:
            connection = client.open_connection()
            if not connection:
                await asyncio.sleep(10)
                continue

            uri = f'{connection["endpoint"]}?ticket={quote_plus(connection["ticket"])}'
            async with websockets.connect(uri) as websocket:
                client.websocket = websocket
                keepalive_task = asyncio.create_task(client.keepalive(websocket))
                try:
                    async for raw_message in websocket:
                        json_message = json.loads(raw_message)
                        await client.route_message(json_message)
                        if done_event.is_set():
                            return
                finally:
                    keepalive_task.cancel()
                    client.websocket = None
        except asyncio.CancelledError:
            raise
        except websockets.exceptions.ConnectionClosed:
            # 连接被服务端断开，重连（除非已收到审核结论）
            if done_event.is_set():
                return
            continue
        except Exception:
            # 其他异常（如网络波动），重连
            if done_event.is_set():
                return
            await asyncio.sleep(3)
            continue


async def _wait_reply_async(app_key: str, app_secret: str,
                            confirm_kws: List[str], cancel_kws: List[str],
                            approver_ids: List[str],
                            timeout_sec: float,
                            enable_feedback: bool = False
                            ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """启动 Stream 长连接，等待审核人回复。返回 (decision, sender_id, feedback)。

    decision ∈ {"confirm", "cancel", "regenerate", None(超时)}
    feedback: 仅 decision="regenerate" 时为用户问题反馈文本
    """
    done_event = asyncio.Event()
    result: Dict[str, Any] = {"decision": None, "sender": None, "feedback": None}
    handler = _ApprovalHandler(done_event, result, confirm_kws, cancel_kws,
                               approver_ids, enable_feedback)

    credential = dingtalk_stream.Credential(app_key, app_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.chatbot.ChatbotMessage.TOPIC, handler
    )

    listener_task = asyncio.create_task(
        run_stream_listener(client, done_event, timeout_sec)
    )
    try:
        try:
            await asyncio.wait_for(done_event.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            return None, None, None
        return result.get("decision"), result.get("sender"), result.get("feedback")
    finally:
        # 优雅停止：关闭 WebSocket 使监听循环退出
        ws = client.websocket
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        listener_task.cancel()
        try:
            await listener_task
        except (asyncio.CancelledError, Exception):
            pass


def wait_for_confirmation(report_text: str, report_name: str,
                          config: Dict[str, Any],
                          regenerate_fn: Optional[Callable[[str, str], str]] = None
                          ) -> Tuple[str, str, str]:
    """向审核人推送周报预览并等待回复，支持根据反馈重新生成后再次审核。

    Args:
        report_text: 待审核的周报文本
        report_name: 周报文件名（用于预览展示）
        config: 全局配置
        regenerate_fn: 可选。审核人取消并给出问题反馈时的重新生成回调，
            签名：regenerate_fn(current_report_text: str, feedback: str) -> str，
            返回重新生成后的完整周报文本。提供后，审核人回复取消关键词会被引导
            提供问题反馈，收到反馈后调用该回调重新生成并再次推送审核，
            直至确认发送、放弃或超时；未提供时保持原行为（取消即放弃）。

    Returns:
        (decision, reason, final_report_text)：
            decision ∈ {"confirm", "cancel", "timeout"}；
            final_report_text 为最终应发送的周报文本（审核过程中可能被重新生成）。
    """
    if not DINGTALK_STREAM_AVAILABLE:
        raise RuntimeError("未安装 dingtalk-stream，请先执行: pip install dingtalk-stream")

    dt_cfg = config.get("dingtalk", {})
    app_key, app_secret = get_credentials(dt_cfg)

    approver_ids = [s.strip() for s in (dt_cfg.get("approver_staff_ids") or []) if str(s).strip()]
    if not approver_ids:
        raise ValueError(
            "dingtalk.approver_staff_ids 未配置。"
            "请先运行 `python dingtalk_userid.py --dept` 获取您的钉钉 userId，再填入配置"
        )

    confirm_kws = dt_cfg.get("confirm_keywords") or DEFAULT_CONFIRM_KEYWORDS
    cancel_kws = dt_cfg.get("cancel_keywords") or DEFAULT_CANCEL_KEYWORDS
    timeout_minutes = float(dt_cfg.get("timeout_minutes", 30))
    max_chars = int(dt_cfg.get("preview_max_chars", 12000))

    current_text = report_text
    round_num = 1

    while True:
        # 1. 推送待审核预览给审核人
        preview = _build_preview(current_text, report_name, confirm_kws, cancel_kws,
                                 timeout_minutes, max_chars, round_num)
        send_markdown_oto(app_key, app_secret, approver_ids, "周报待审核", preview)
        logger.info("钉钉待审核预览已发送给审核人: %s（第 %d 版）", ", ".join(approver_ids), round_num)
        logger.info("等待审核人回复（%s 确认 / %s 提出修改意见），超时 %g 分钟自动放弃...",
                    "/".join(confirm_kws), "/".join(cancel_kws), timeout_minutes)

        # 2. 启动 Stream 长连接等待回复
        decision, sender, feedback = asyncio.run(_wait_reply_async(
            app_key, app_secret, confirm_kws, cancel_kws,
            approver_ids, timeout_minutes * 60,
            enable_feedback=regenerate_fn is not None,
        ))

        if decision == "confirm":
            return "confirm", f"审核人 {sender or '(未知)'} 已确认发送", current_text
        if decision == "cancel":
            return "cancel", f"审核人 {sender or '(未知)'} 已取消发送", current_text
        if decision == "regenerate":
            # 3. 收到问题反馈：通知审核人正在重新生成
            if regenerate_fn is None:
                return "cancel", f"审核人 {sender or '(未知)'} 已取消发送", current_text
            try:
                send_markdown_oto(
                    app_key, app_secret, approver_ids, "周报重新生成中",
                    "## 周报重新生成中\n\n已收到您的反馈，正在根据反馈重新生成周报，"
                    f"完成后将再次发送给您审核。\n\n**反馈内容**：\n\n{feedback}",
                )
            except Exception as e:
                logger.warning("重新生成进度通知发送失败: %s", e)
            # 4. 调用重新生成回调（把反馈发送给大模型重新生成）
            try:
                current_text = regenerate_fn(current_text, feedback)
                round_num += 1
                logger.info("已根据审核人反馈重新生成周报（第 %d 版），重新推送审核", round_num)
                continue  # 循环：推送新版预览再次审核
            except Exception as e:
                logger.error("根据反馈重新生成周报失败: %s", e)
                try:
                    send_markdown_oto(
                        app_key, app_secret, approver_ids, "周报重新生成失败",
                        "## 周报重新生成失败\n\n根据您的反馈重新生成周报时出错：\n\n"
                        f"{e}\n\n请回复「发送」确认发送当前版本，或回复「取消」重新提供反馈，"
                        f"或回复「放弃」取消本次发送。",
                    )
                except Exception:
                    pass
                continue  # 重新推送当前版本供审核人决定

        # 5. 超时：通知审核人
        try:
            send_markdown_oto(
                app_key, app_secret, approver_ids, "周报审核超时",
                f"## 周报审核超时\n\n超过 {timeout_minutes:g} 分钟未收到确认回复，"
                f"本次周报（{report_name}）未发送。\n\n如需发送请重新运行生成流程。",
            )
        except Exception as e:
            logger.warning("超时通知发送失败: %s", e)
        return "timeout", f"超过 {timeout_minutes:g} 分钟未收到回复", current_text


def send_dingtalk_report(report_text: str, report_name: str,
                         config: Dict[str, Any]) -> None:
    """审核通过后，将周报推送给钉钉接收人（单聊 + 群聊）。"""
    dt_cfg = config.get("dingtalk", {})
    if not dt_cfg.get("enabled"):
        return

    app_key, app_secret = get_credentials(dt_cfg)
    max_chars = int(dt_cfg.get("preview_max_chars", 12000))
    title = report_name or "周报"
    text = f"## {title}\n\n" + _truncate(report_text, max_chars)

    recipient_ids = [s.strip() for s in (dt_cfg.get("recipient_staff_ids") or []) if str(s).strip()]
    conversation_id = str(dt_cfg.get("open_conversation_id") or "").strip()
    if not recipient_ids and not conversation_id:
        logger.warning("dingtalk.recipient_staff_ids 与 open_conversation_id 均未配置，跳过钉钉发送")
        return

    if recipient_ids:
        send_markdown_oto(app_key, app_secret, recipient_ids, title, text)
        logger.info("钉钉周报已发送（单聊）: %s", ", ".join(recipient_ids))
    if conversation_id:
        send_markdown_group(app_key, app_secret, conversation_id, title, text)
        logger.info("钉钉周报已发送（群聊）: %s", conversation_id)


def send_failure_alert(config: Dict[str, Any], error_summary: str) -> None:
    """主流程失败时，向审核人推送告警通知（钉钉单聊）。

    适用于 CRM 下载失败、AI 生成失败、发送失败等异常场景。
    若钉钉未启用或审核人未配置，则静默跳过（不阻断主流程）。
    通知模板：config.json 的 notification.templates.failure_alert。
    """
    dt_cfg = config.get("dingtalk", {})
    if not dt_cfg.get("enabled"):
        return
    approver_ids = [s.strip() for s in (dt_cfg.get("approver_staff_ids") or []) if str(s).strip()]
    if not approver_ids:
        return
    try:
        app_key, app_secret = get_credentials(dt_cfg)
    except ValueError:
        return
    # 从配置模板渲染告警文本
    try:
        from config_manager import render_notification
        title, text = render_notification(config, "failure_alert", error_summary=error_summary)
    except KeyError as e:
        # 模板缺失时使用硬编码兜底
        logger.warning("%s，使用默认告警格式", e)
        title = "周报生成失败"
        text = f"## 周报生成失败\n\n本周周报自动生成流程出现异常，详情如下：\n\n{error_summary}\n\n请检查日志或联系系统管理员处理。"
    try:
        send_markdown_oto(app_key, app_secret, approver_ids, title, text)
        logger.info("失败告警已发送给审核人: %s", ", ".join(approver_ids))
    except Exception as e:
        logger.warning("失败告警发送失败: %s", e)
