# -*- coding: utf-8 -*-
"""配置管理模块。

负责：
- 定义 PROVIDER_PRESETS（各 AI provider 的默认配置）
- 定义 DEFAULT_CONFIG（首次运行写入 config.json 的默认配置）
- 加载 config.json 并合并默认值、环境变量
"""
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

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
        "token": "",                                 # authorization 头中 Bearer: 后的 JWT token（失效时自动用 login_url 刷新）
        "userid": "",                                # 请求头 userid 字段（CRM 用户 ID）
        "tyinjectparams": "",                        # 请求头 tyinjectparams 字段（可选，CRM 注入参数）
        "org_oid_list": [],                          # 组织 OID 列表
        "user_oid_list": [],                         # 用户 OID 列表（可选）
        "project_oid_list": [],                      # 项目 OID 列表（可选）
        "download_dir": "excel_files",               # 下载保存目录（相对脚本目录或绝对路径）
        "timeout": 60,                               # CRM 接口请求超时（秒）
        "login_url": "https://crm.example.com/rest/userService/v1/user/userLoginPlm",
        "username": "",                             # CRM 登录账号（如 T0265），用于 token 失效时自动刷新
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
    },
}

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> Dict[str, Any]:
    """加载配置：config.json > 环境变量 > 默认值。"""
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[INFO] 已生成配置模板: {CONFIG_PATH}")
        print("[INFO] 请编辑 config.json 填入对应 provider 的 api_key、excel_folder 后重新运行。")
        sys.exit(0)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 环境变量覆盖（便于 CI / 容器部署）
    # 支持为每个 provider 单独设置 api_key: MINIMAX_API_KEY / DEEPSEEK_API_KEY / OPENCODE_API_KEY / QWEN_API_KEY
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

    # 合并默认值（兼容旧 config 缺字段的情况）
    for k, v in DEFAULT_CONFIG.items():
        config.setdefault(k, v)
    # 确保 providers 中四个 provider 都存在（兼容旧版配置升级）
    for prov_name, preset in PROVIDER_PRESETS.items():
        config["providers"].setdefault(prov_name, preset)
        # 补齐新增字段（如 thinking_param / max_tokens_field）
        for k, v in preset.items():
            config["providers"][prov_name].setdefault(k, v)
    # 确保 email 配置段存在且字段完整（兼容旧版配置升级）
    email_default = DEFAULT_CONFIG.get("email", {})
    config.setdefault("email", {})
    for k, v in email_default.items():
        config["email"].setdefault(k, v)
    # 确保 crm 配置段存在且字段完整（兼容旧版配置升级）
    crm_default = DEFAULT_CONFIG.get("crm", {})
    config.setdefault("crm", {})
    for k, v in crm_default.items():
        config["crm"].setdefault(k, v)
    # 环境变量覆盖 CRM 配置（便于 CI / 容器部署，避免明文存储）
    if os.getenv("CRM_TOKEN"):
        config["crm"]["token"] = os.environ["CRM_TOKEN"]
    if os.getenv("CRM_USERNAME"):
        config["crm"]["username"] = os.environ["CRM_USERNAME"]
    if os.getenv("CRM_PASSWORD"):
        config["crm"]["password"] = os.environ["CRM_PASSWORD"]
    # 环境变量覆盖邮箱密码（便于 CI / 容器部署）
    if os.getenv("EMAIL_PASSWORD"):
        config["email"]["password"] = os.environ["EMAIL_PASSWORD"]
    return config
