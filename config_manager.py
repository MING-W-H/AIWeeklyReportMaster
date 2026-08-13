# -*- coding: utf-8 -*-
"""配置管理模块。

负责：
- 定义 PROVIDER_PRESETS（各 AI provider 的默认配置）
- 定义 DEFAULT_CONFIG（首次运行写入 config.json 的默认配置）
- 加载 config.json 并合并默认值、环境变量
"""
import copy
import difflib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from logger import get_logger

logger = get_logger(__name__)

# ============ 自动加载 .env 文件 ============
# 优先级：进程环境变量 > .env 文件 > config.json
# .env 文件已在 .gitignore 中忽略，不会提交到 git
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv 未安装时跳过，不影响环境变量直接使用
    pass


# ============ Provider 默认配置 ============
# 四家均为 OpenAI 兼容协议，仅 base_url / model / 默认参数不同
PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    "minimax": {
        "api_key": "",                                            # 填入 MiniMax API Key
        "base_url": "https://api.minimaxi.com/v1/chat/completions",
        "model": "MiniMax-M3",
        "thinking_param": {"type": "adaptive"},                  # M3 思考模式参数
        "max_tokens_field": "max_completion_tokens",
    },
    "deepseek": {
        "api_key": "",                                            # 填入 DeepSeek API Key
        "base_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-v4-flash",                             # 也可用 deepseek-v4-pro
        "thinking_param": {"type": "enabled"},                   # DeepSeek 思考模式参数
        "max_tokens_field": "max_completion_tokens",
    },
    "opencode": {
        "api_key": "",                                            # 填入 OpenCode Zen API Key
        "base_url": "https://opencode.ai/zen/v1/chat/completions",
        "model": "glm-5.2",                                       # GLM 5.2 模型，也可用 gpt-5.5、deepseek-v4-flash 等
        "thinking_param": None,                                   # OpenCode 不支持 thinking 参数
        "max_tokens_field": "max_tokens",
    },
    "qwen": {
        "api_key": "",                                            # 填入阿里云 DashScope API Key
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen3.8-max-preview",                           # 通义千问 Qwen 3.8 Max Preview
        "thinking_param": None,                                   # Qwen 暂不支持 thinking 参数
        "max_tokens_field": "max_tokens",
    },
}

# ============ 默认配置（首次运行会写入 config.json） ============
DEFAULT_CONFIG: Dict[str, Any] = {
    "provider": "minimax",                           # 当前使用的 provider: minimax | deepseek | opencode | qwen
    "fallback_providers": [],                        # 备用 provider 列表，主 provider 失败时依次降级（如 ["deepseek", "qwen"]）
    "providers": PROVIDER_PRESETS,                   # 多 provider 配置（可自由修改 base_url/model）
    "excel_folder": "./excel_files",                 # Excel 文件所在文件夹（绝对路径或相对路径）
    "excel_extensions": [".xlsx", ".xls", ".xlsm"],  # 支持的 Excel 扩展名
    "output_format": "markdown",                     # markdown | plain | structured | bullet | custom
    "output_folder": "reports",                       # 周报输出文件夹（相对于脚本所在目录，或绝对路径）
    "output_file_template": "Vue{last_week_range}周报",  # 输出文件名模板，{last_week_range} = 上一周日期范围
    "output_file": "",                               # 若设置则直接使用该路径，覆盖 template
    "tokens_to_generate": 4096,
    "temperature": 0.3,
    "max_chars_per_sheet": 30000,                    # 单个 sheet 文本最大字符数（防止超 token）
    "custom_prompt": "",                             # output_format=custom 时使用
    "thinking_enabled": False,                       # 是否开启思考模式（DeepSeek/MiniMax 生效）
    "timeout": 180,
    "crm": {                                         # CRM 工时接口配置（启用后自动从接口下载 Excel，无需手动放置）
        "enabled": False,                            # 是否启用 CRM 接口下载（启用后忽略 excel_folder 手动放置的文件）
        "url": "https://crm.example.com/ipd/rest/v1/workHourReport/integration/exportWorkHourItems",
        "token": "",                                 # authorization 头中 Bearer: 后的 JWT token（失效时自动刷新并加密落盘）
        "userid": "",                                # 请求头 userid 字段（CRM 用户 ID）
        "tyinjectparams": "",                        # 请求头 tyinjectparams 字段（可选，CRM 注入参数）
        "org_oid_list": [],                          # 组织 OID 列表
        "user_oid_list": [],                         # 用户 OID 列表（可选）
        "project_oid_list": [],                      # 项目 OID 列表（可选）
        "download_dir": "excel_files",               # 下载保存目录（相对脚本目录或绝对路径）
        "export_prefix": "",                         # 下载文件名前缀（如团队名，可留空），例如 "{export_prefix}2026.7.13-7.17.xlsx"
        "timeout": 60,                               # CRM 接口请求超时（秒）
        "login_url": "https://crm.example.com/rest/userService/v1/user/userLoginPlm",
        "username": "",                             # CRM 登录账号（如 user001），用于 token 失效时自动刷新
        "password": "",                             # CRM 登录密码（加密后的字符串，敏感，建议用环境变量 CRM_PASSWORD）
        "app_id": "Chrome(149.0.0.0)",              # 登录请求体 appID 字段
    },
    "email": {                                       # 腾讯企业邮箱配置
        "enabled": False,                            # 是否在生成周报后自动发送邮件
        "smtp_host": "smtp.exmail.qq.com",           # 腾讯企业邮箱 SMTP 服务器
        "smtp_port": 465,                            # SSL 端口
        "sender": "",                                # 发件人邮箱（企业邮箱地址）
        "password": "",                              # 发件人密码（或客户端专用密码）
        "recipients": [],                            # 收件人列表，如 ["a@company.com", "b@company.com"]
        "cc": [],                                    # 抄送列表（可选）
        "subject_template": "Vue 周报 {last_week_range}",  # 邮件主题模板
        "attach_report": True,                       # 是否将周报文件作为附件发送
        "max_chars": 30000,                          # 邮件正文最大字符数（超出截断并告警）
    },
    "contact_info": {                                # 个人联系方式（用于通知消息）
        "email": "your_email@example.com",            # 邮箱
        "phone": "13800138000",                       # 手机号
        "dingtalk": "本机器人",                        # 钉钉说明
    },
    "notification": {                                 # 消息通知模板（钉钉 Markdown 格式）
        "templates": {                                # 多通知类型模板
            "weekly_notice": {                        # 周报通知（dingtalk_send_notice.py 用）
                "title": "周报通知",
                "template": (
                    "**各位领导好：**\n\n"
                    "**重要通知：** 自本周起，周报将统一通过本钉钉机器人发送，"
                    "后续请留意机器人消息提醒，及时查收周报内容。\n\n"
                    "---\n\n"
                    "**联系方式**\n"
                    "- 钉钉：{dingtalk}\n"
                    "- 邮箱：{email}\n"
                    "- 电话：{phone}\n\n"
                    "---\n\n"
                    "{footer}"
                ),
            },
            "failure_alert": {                        # 失败告警（send_failure_alert() 用）
                "title": "周报生成失败",
                "template": (
                    "## 周报生成失败\n\n"
                    "本周周报自动生成流程出现异常，详情如下：\n\n"
                    "{error_summary}\n\n"
                    "请检查日志或联系系统管理员处理。\n\n"
                    "---\n\n"
                    "**联系方式**\n"
                    "- 钉钉：{dingtalk}\n"
                    "- 邮箱：{email}\n"
                    "- 电话：{phone}"
                ),
            },
            "crm_reminder": {                         # CRM 填写提醒（crm_reminder.py 用）
                "title": "CRM 填写提醒",
                "template": (
                    "## 周五 CRM 填写提醒\n\n"
                    "{names}\n\n"
                    "请记得在今天下班前完成 **CRM 工时填写**，谢谢配合！\n\n"
                    "- **截止时间**：今天 17:00 前\n\n"
                    "---\n\n"
                    "{footer}"
                ),
            },
        },
    },
    "retry": {                                        # 网络请求重试配置
        "max_retries": 2,                             # 最大重试次数（不含首次）
        "base_delay": 1.0,                            # 首次重试等待秒数
        "backoff": 2.0,                               # 退避因子
    },
    "dingtalk": {                                    # 钉钉人工审核 + 推送配置（企业内部应用机器人 Stream 模式）
        "enabled": False,                            # 启用后 AI 生成周报需经审核人回复确认才发送
        "app_key": "",                               # Client ID（建议放 .env: DINGTALK_APP_KEY）
        "app_secret": "",                            # Client Secret（建议放 .env: DINGTALK_APP_SECRET）
        "approver_staff_ids": [],                    # 审核人 userId 列表（运行 dingtalk_userid.py --dept 获取）
        "recipient_staff_ids": [],                   # 周报钉钉接收人 userId 列表（单聊推送）
        "open_conversation_id": "",                  # 周报钉钉接收群 openConversationId（群聊推送，可选）
        "confirm_keywords": ["发送", "send", "确认", "ok"],   # 确认发送关键词
        "cancel_keywords": ["取消", "cancel", "放弃", "不发送"],  # 取消发送关键词
        "timeout_minutes": 30,                       # 等待审核回复超时时间（分钟）
        "preview_max_chars": 12000,                  # 钉钉 Markdown 消息最大字符数（超出截断）
    },
    "attendance": {                                  # 考勤查询配置（attendance_checker.py 用）
        "user_ids": [],                              # 默认查询的考勤 userId 列表（未传 --userids/--dept 时使用）
        "start_date": "",                            # 查询开始日期 YYYY-MM-DD，留空则默认最近 7 天（--start 优先）
        "end_date": "",                              # 查询结束日期 YYYY-MM-DD，留空则默认今天（--end 优先）
        "output_folder": "attendance_output",        # Excel 导出文件夹（数据含员工考勤信息，已被 gitignore 忽略）
    },
    "crm_reminder": {                                # CRM 填写提醒配置（crm_reminder.py 用，每周五定时发钉钉群）
        "enabled": False,                            # 是否启用 CRM 填写提醒
        "send_weekday": 4,                           # 每周几发送：0=周一 ... 6=周日（默认 4=周五）
        "skip_holiday": True,                        # 法定节假日/周末自动跳过（复用 holiday_checker）
        "conversation_id": "",                       # 目标钉钉群 openConversationId（留空回退 dingtalk.open_conversation_id）
        "remind_user_ids": [],                        # 需要 @ 的成员 userId 列表（运行 dingtalk_userid.py --dept 获取）
    },
    "chatbot": {                                     # 钉钉 AI 问答机器人配置（dingtalk_chatbot.py 用，大模型回答用户问题）
        "enabled": False,                            # 是否启用 AI 问答机器人
        "system_prompt": (                           # 预设系统提示词（人设参数），发送给大模型的机器人身份与行为约束
            "你是公司的 AI 周报机器人，"
            "由公司内部开发，服务于员工。"
            "你可以回答与周报系统、CRM 工时填写、公司日常事务等相关的各类问题。\n\n"
            "行为准则：\n"
            "1. 使用简体中文回答，语言专业、简洁、友好\n"
            "2. 涉及不确定或不清楚的信息时，如实说明，不要编造\n"
            "3. 涉及个人隐私或公司机密的信息，礼貌地表示不便回答\n"
            "4. 回答先给结论再给理由，不要使用 Markdown 表格"
        ),
        "allow_user_ids": [],                        # 允许使用机器人的用户 userId 白名单（留空=全部员工）
        "max_history_turns": 10,                     # 每个会话保留的对话轮数（多轮上下文）
        "max_reply_chars": 8000,                     # 单条回复最大字符数（超出截断）
        "reset_keywords": ["清空", "清空对话", "重置", "重置对话", "/clear"],  # 清空对话上下文关键词
    },
}

CONFIG_PATH = Path(__file__).parent / "config.json"

# 需要合并默认值的配置段列表（新增配置段时在此追加）
_SECTIONS_TO_MERGE = ("email", "crm", "dingtalk", "attendance", "crm_reminder", "chatbot")


def _merge_config_section(config: Dict[str, Any], section_name: str) -> None:
    """合并单个配置段的默认值（原地更新，兼容旧版配置升级）。

    Args:
        config: 全局配置字典（会原地更新）
        section_name: 配置段名称（如 "email"、"crm"、"dingtalk"）
    """
    section_default = DEFAULT_CONFIG.get(section_name, {})
    config.setdefault(section_name, {})
    for k, v in section_default.items():
        config[section_name].setdefault(k, v)


def _merge_providers_config(config: Dict[str, Any]) -> None:
    """合并 providers 配置：确保四个 provider 都存在且字段完整。"""
    for prov_name, preset in PROVIDER_PRESETS.items():
        config["providers"].setdefault(prov_name, copy.deepcopy(preset))
        # 补齐新增字段（如 thinking_param / max_tokens_field）
        for k, v in preset.items():
            config["providers"][prov_name].setdefault(k, v)


def _merge_notification_templates(config: Dict[str, Any]) -> None:
    """合并 notification.templates 配置：确保各通知模板存在。"""
    config["notification"].setdefault("templates", {})
    for k, v in DEFAULT_CONFIG.get("notification", {}).get("templates", {}).items():
        config["notification"]["templates"].setdefault(k, v)


def _apply_env_overrides(config: Dict[str, Any]) -> None:
    """应用环境变量覆盖到配置字典（原地更新，便于 CI / 容器部署）。

    优先级：环境变量 > config.json。敏感信息（密码/凭证）建议用环境变量注入。
    """
    # 各 provider 的 API Key: MINIMAX_API_KEY / DEEPSEEK_API_KEY / OPENCODE_API_KEY / QWEN_API_KEY
    env_key_map = {
        "minimax": "MINIMAX_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "opencode": "OPENCODE_API_KEY",
        "qwen": "QWEN_API_KEY",
    }
    for prov_name, env_var in env_key_map.items():
        env_val = os.getenv(env_var)
        if env_val:
            config.setdefault("providers", {}).setdefault(prov_name, {})["api_key"] = env_val
    if os.getenv("EXCEL_FOLDER"):
        config["excel_folder"] = os.environ["EXCEL_FOLDER"]
    # CRM 配置（避免明文存储）
    if os.getenv("CRM_TOKEN"):
        config["crm"]["token"] = os.environ["CRM_TOKEN"]
    if os.getenv("CRM_USERNAME"):
        config["crm"]["username"] = os.environ["CRM_USERNAME"]
    if os.getenv("CRM_PASSWORD"):
        config["crm"]["password"] = os.environ["CRM_PASSWORD"]
    # 邮箱密码（便于 CI / 容器部署）
    if os.getenv("EMAIL_PASSWORD"):
        config["email"]["password"] = os.environ["EMAIL_PASSWORD"]
    # 钉钉凭证（敏感信息不写入 config.json）
    if os.getenv("DINGTALK_APP_KEY"):
        config["dingtalk"]["app_key"] = os.environ["DINGTALK_APP_KEY"]
    if os.getenv("DINGTALK_APP_SECRET"):
        config["dingtalk"]["app_secret"] = os.environ["DINGTALK_APP_SECRET"]


# ============ 配置 Schema 校验 ============
# 用于在加载时尽早暴露 config.json 中的字段名拼写错误与类型错误。
# 结构说明：
#   type       必填，期望类型（tuple 表示多种允许类型）
#   choices    可选，允许取值集合（枚举校验）
#   allow_extra 可选，dict 是否允许未知字段（默认 False，固定结构禁止拼写错误）
#   fields     可选，固定结构 dict 的子字段描述
#   item_type  可选，动态 key dict（如 providers）或 list 的元素结构描述
_CONFIG_SCHEMA: Dict[str, Any] = {
    "type": dict,
    "allow_extra": False,
    "fields": {
        "provider": {"type": str, "choices": ["minimax", "deepseek", "opencode", "qwen"]},
        "fallback_providers": {"type": list, "item_type": {"type": str}},
        "providers": {
            "type": dict,
            "allow_extra": True,   # 允许自定义 provider（key 任意）
            "item_type": {
                "type": dict,
                "allow_extra": False,
                "fields": {
                    "api_key": {"type": str},
                    "base_url": {"type": str},
                    "model": {"type": str},
                    "thinking_param": {"type": (dict, type(None))},
                    "max_tokens_field": {"type": str},
                },
            },
        },
        "excel_folder": {"type": str},
        "excel_extensions": {"type": list, "item_type": {"type": str}},
        "output_format": {"type": str, "choices": ["markdown", "plain", "structured", "bullet", "custom"]},
        "output_folder": {"type": str},
        "output_file_template": {"type": str},
        "output_file": {"type": str},
        "tokens_to_generate": {"type": int},
        "temperature": {"type": (int, float)},
        "max_chars_per_sheet": {"type": int},
        "custom_prompt": {"type": str},
        "thinking_enabled": {"type": bool},
        "timeout": {"type": int},
        "crm": {
            "type": dict,
            "allow_extra": False,
            "fields": {
                "enabled": {"type": bool},
                "url": {"type": str},
                "token": {"type": str},
                "userid": {"type": str},
                "tyinjectparams": {"type": str},
                "org_oid_list": {"type": list, "item_type": {"type": str}},
                "user_oid_list": {"type": list, "item_type": {"type": str}},
                "project_oid_list": {"type": list, "item_type": {"type": str}},
                "download_dir": {"type": str},
                "export_prefix": {"type": str},
                "timeout": {"type": int},
                "login_url": {"type": str},
                "username": {"type": str},
                "password": {"type": str},
                "app_id": {"type": str},
            },
        },
        "email": {
            "type": dict,
            "allow_extra": False,
            "fields": {
                "enabled": {"type": bool},
                "smtp_host": {"type": str},
                "smtp_port": {"type": int},
                "sender": {"type": str},
                "password": {"type": str},
                "recipients": {"type": list, "item_type": {"type": str}},
                "cc": {"type": list, "item_type": {"type": str}},
                "subject_template": {"type": str},
                "attach_report": {"type": bool},
                "max_chars": {"type": int},
            },
        },
        "contact_info": {
            "type": dict,
            "allow_extra": False,
            "fields": {
                "email": {"type": str},
                "phone": {"type": str},
                "dingtalk": {"type": str},
            },
        },
        "notification": {
            "type": dict,
            "allow_extra": False,
            "fields": {
                "templates": {
                    "type": dict,
                    "allow_extra": True,   # 允许新增自定义通知模板
                    "item_type": {
                        "type": dict,
                        "allow_extra": False,
                        "fields": {
                            "title": {"type": str},
                            "template": {"type": str},
                        },
                    },
                },
            },
        },
        "retry": {
            "type": dict,
            "allow_extra": False,
            "fields": {
                "max_retries": {"type": int},
                "base_delay": {"type": (int, float)},
                "backoff": {"type": (int, float)},
            },
        },
        "dingtalk": {
            "type": dict,
            "allow_extra": False,
            "fields": {
                "enabled": {"type": bool},
                "app_key": {"type": str},
                "app_secret": {"type": str},
                "approver_staff_ids": {"type": list, "item_type": {"type": str}},
                "recipient_staff_ids": {"type": list, "item_type": {"type": str}},
                "open_conversation_id": {"type": str},
                "confirm_keywords": {"type": list, "item_type": {"type": str}},
                "cancel_keywords": {"type": list, "item_type": {"type": str}},
                "timeout_minutes": {"type": (int, float)},
                "preview_max_chars": {"type": int},
            },
        },
        "attendance": {
            "type": dict,
            "allow_extra": False,
            "fields": {
                "user_ids": {"type": list, "item_type": {"type": str}},
                "start_date": {"type": str},
                "end_date": {"type": str},
                "output_folder": {"type": str},
            },
        },
        "crm_reminder": {
            "type": dict,
            "allow_extra": False,
            "fields": {
                "enabled": {"type": bool},
                "send_weekday": {"type": int, "choices": list(range(7))},
                "skip_holiday": {"type": bool},
                "conversation_id": {"type": str},
                "remind_user_ids": {"type": list, "item_type": {"type": str}},
            },
        },
        "chatbot": {
            "type": dict,
            "allow_extra": False,
            "fields": {
                "enabled": {"type": bool},
                "system_prompt": {"type": str},
                "allow_user_ids": {"type": list, "item_type": {"type": str}},
                "max_history_turns": {"type": int},
                "max_reply_chars": {"type": int},
                "reset_keywords": {"type": list, "item_type": {"type": str}},
            },
        },
    },
}


def _type_name(t: Any) -> str:
    """将类型对象转换为人类可读的中文名称。"""
    if isinstance(t, tuple):
        return "/".join(_type_name(x) for x in t)
    if t is type(None):
        return "null"
    if t is str:
        return "字符串"
    if t is int:
        return "整数"
    if t is float:
        return "数字"
    if t is bool:
        return "布尔值"
    if t is list:
        return "数组"
    if t is dict:
        return "对象"
    return getattr(t, "__name__", str(t))


def _guess_similar(name: str, fields: Dict[str, Any]) -> str:
    """根据相近拼写猜测正确字段名（如 apikey → api_key）。"""
    candidates = difflib.get_close_matches(name, fields.keys(), n=1, cutoff=0.6)
    return f"（可能是「{candidates[0]}」拼写错误）" if candidates else "（字段名拼写错误）"


def _validate_value(value: Any, schema: Dict[str, Any], path: str, errors: List[str]) -> None:
    """递归校验单个配置值，错误信息追加到 errors 列表。"""
    expected = schema["type"]

    # bool 是 int 的子类，需先单独处理，避免 true/false 通过整数校验
    if expected is bool:
        if not isinstance(value, bool):
            errors.append(f"{path} 类型错误：期望 {_type_name(expected)}，当前是 {type(value).__name__}: {value!r}")
            return
    elif isinstance(value, bool):
        errors.append(f"{path} 类型错误：期望 {_type_name(expected)}，当前是布尔值 {value!r}")
        return
    elif not isinstance(value, expected):
        errors.append(f"{path} 类型错误：期望 {_type_name(expected)}，当前是 {type(value).__name__}: {value!r}")
        return

    if "choices" in schema and value not in schema["choices"]:
        allowed = " / ".join(str(c) for c in schema["choices"])
        errors.append(f"{path} 取值非法：期望 {allowed}，当前值: {value!r}")
        return

    if isinstance(value, dict):
        item_schema = schema.get("item_type")
        if item_schema is not None:
            for k, v in value.items():
                _validate_value(v, item_schema, f"{path}.{k}", errors)
            return
        fields = schema.get("fields")
        if fields is not None:
            if not schema.get("allow_extra", False):
                unknown = set(value.keys()) - set(fields.keys())
                for k in sorted(unknown):
                    errors.append(f"{path} 包含未知字段: {k} {_guess_similar(k, fields)}")
            for k, sub in fields.items():
                if k in value:
                    _validate_value(value[k], sub, f"{path}.{k}", errors)

    elif isinstance(value, list):
        item_type = schema.get("item_type")
        if item_type is not None:
            for i, v in enumerate(value):
                _validate_value(v, item_type, f"{path}[{i}]", errors)


def validate_config(config: Dict[str, Any]) -> List[str]:
    """按 _CONFIG_SCHEMA 校验配置字典，返回错误信息列表（空列表 = 校验通过）。"""
    errors: List[str] = []
    _validate_value(config, _CONFIG_SCHEMA, "config", errors)
    return errors


def validate_required_config(config: Dict[str, Any]) -> List[str]:
    """校验「已启用功能」的关键配置是否齐全，返回缺失项列表（空列表 = 通过）。

    与 validate_config（字段类型/拼写校验）互补：本函数关注关键凭证是否缺失，
    仅在功能启用时才校验对应配置，避免误报未启用的模块。
    """
    errors: List[str] = []

    # 1. AI provider：至少一个 provider 配置了 api_key（否则无法生成周报）
    providers = config.get("providers", {})
    configured = [p for p, cfg in providers.items() if cfg.get("api_key", "").strip()]
    if not configured:
        errors.append(
            "未配置任何 AI provider 的 api_key。"
            "请在 config.json 的 providers.{minimax|deepseek|opencode|qwen}.api_key 中填写，"
            "或设置环境变量（MINIMAX_API_KEY / DEEPSEEK_API_KEY / OPENCODE_API_KEY / QWEN_API_KEY）"
        )

    # 2. CRM：启用时需能拿到 token（直接配置/环境变量，或具备自动登录刷新能力）
    crm = config.get("crm", {})
    if crm.get("enabled"):
        if not crm.get("url", "").strip():
            errors.append("crm.enabled=true 但 crm.url 未设置")
        token = crm.get("token", "").strip() or os.getenv("CRM_TOKEN", "").strip()
        if not token:
            login_ready = (
                crm.get("login_url", "").strip()
                and (os.getenv("CRM_USERNAME", "").strip() or crm.get("username", "").strip())
                and (os.getenv("CRM_PASSWORD", "").strip() or crm.get("password", "").strip())
            )
            if not login_ready:
                errors.append(
                    "crm.enabled=true 但缺少可用凭证：既无 crm.token/CRM_TOKEN，"
                    "也无完整自动登录配置（crm.login_url + crm.username + crm.password）"
                )

    # 3. 邮件：启用时需配置发件人 / 密码 / 收件人
    email = config.get("email", {})
    if email.get("enabled"):
        sender = os.getenv("EMAIL_SENDER", "").strip() or email.get("sender", "").strip()
        password = os.getenv("EMAIL_PASSWORD", "").strip() or email.get("password", "").strip()
        if not sender:
            errors.append("email.enabled=true 但未配置发件人（email.sender 或环境变量 EMAIL_SENDER）")
        if not password:
            errors.append("email.enabled=true 但未配置邮箱密码（email.password 或环境变量 EMAIL_PASSWORD）")
        if not email.get("recipients"):
            errors.append("email.enabled=true 但 email.recipients 为空，请至少填入一个收件人")

    # 4. 钉钉：启用时需配置 app_key / app_secret
    dingtalk = config.get("dingtalk", {})
    if dingtalk.get("enabled"):
        if not dingtalk.get("app_key", "").strip():
            errors.append("dingtalk.enabled=true 但未配置 app_key（或环境变量 DINGTALK_APP_KEY）")
        if not dingtalk.get("app_secret", "").strip():
            errors.append("dingtalk.enabled=true 但未配置 app_secret（或环境变量 DINGTALK_APP_SECRET）")

    return errors


def load_config() -> Dict[str, Any]:
    """加载配置：环境变量 > config.json > 默认值。"""
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("已生成配置模板: %s", CONFIG_PATH)
        logger.info("请编辑 config.json 填入对应 provider 的 api_key、excel_folder 后重新运行。")
        sys.exit(0)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 合并顶层默认值（兼容旧 config 缺字段的情况）
    for k, v in DEFAULT_CONFIG.items():
        if k not in config:
            config[k] = copy.deepcopy(v)

    # 合并嵌套配置段默认值（兼容旧版配置升级）
    _merge_providers_config(config)
    for section in _SECTIONS_TO_MERGE:
        _merge_config_section(config, section)
    config.setdefault("contact_info", DEFAULT_CONFIG.get("contact_info", {}))
    config.setdefault("notification", DEFAULT_CONFIG.get("notification", {}))
    _merge_notification_templates(config)
    config.setdefault("retry", DEFAULT_CONFIG.get("retry", {}))

    # 环境变量覆盖（优先级最高）
    _apply_env_overrides(config)

    # Schema 校验：尽早暴露字段名拼写错误与类型错误
    errors = validate_config(config)
    if errors:
        raise ValueError(
            "config.json 校验失败，请修正以下问题：\n  - " + "\n  - ".join(errors)
        )
    return config


def render_notification(config: Dict[str, Any], template_name: str, **kwargs) -> Tuple[str, str]:
    """渲染通知模板，返回 (title, text)。

    Args:
        config: 已加载的配置字典
        template_name: 模板名称（如 "weekly_notice", "failure_alert"）
        **kwargs: 模板占位符的值（如 error_summary="xxx", footer="yyy"）

    Returns:
        (title, text) — 消息标题与正文

    自动注入 contact_info 中的 {dingtalk}/{email}/{phone} 占位符，
    调用方无需手动传入联系方式。
    """
    templates = config.get("notification", {}).get("templates", {})
    tpl = templates.get(template_name)
    if not tpl:
        raise KeyError(f"通知模板 '{template_name}' 不存在，请检查 config.json notification.templates")
    title = tpl.get("title", template_name)
    template = tpl.get("template", "")

    # 自动注入联系方式占位符
    contact = config.get("contact_info", {})
    render_kwargs = {
        "dingtalk": contact.get("dingtalk", "本机器人"),
        "email": contact.get("email", ""),
        "phone": contact.get("phone", ""),
        "footer": "",
    }
    # 调用方传入的值优先
    render_kwargs.update(kwargs)

    text = template.format(**render_kwargs)
    return title, text
