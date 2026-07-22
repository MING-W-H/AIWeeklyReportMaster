# -*- coding: utf-8 -*-
"""LLM API 调用模块。

负责通过 OpenAI 兼容协议调用各 AI provider（minimax/deepseek/opencode/qwen），
生成周报文本。包含详细的错误处理（HTTP 状态码、超时、网络异常等）。
"""
from typing import Any, Dict

import requests

from text_utils import strip_chat_prefix


# ============ 输出格式对应的系统提示词 ============
FORMAT_TEMPLATES: Dict[str, str] = {
    "markdown": (
        "请将以下 Excel 汇总数据整理为 Markdown 格式的周报，按以下结构输出：\n\n"
        "# 周报\n\n"
        "## 一、本周工作概览\n"
        "（简述本周整体工作情况、核心成果）\n\n"
        "## 二、主要工作进展\n"
        "（按项目/模块分小节列出关键进展，使用项目符号 `-`）\n\n"
        "## 三、关键数据指标\n"
        "（如包含数值数据，整理为 Markdown 表格展示）\n\n"
        "## 四、问题与解决方案\n"
        "（列出遇到的问题、潜在风险及对应的解决方案或建议）\n\n"
        "要求：语言简练、重点突出、数据准确，避免无意义的套话。"
    ),
    "plain": (
        "请将以下 Excel 汇总数据整理为纯文本格式的周报，使用清晰的段落分隔，"
        "包含以下部分：本周工作概览、主要工作进展、关键数据指标、问题与解决方案。"
        "语言简练、重点突出。"
    ),
    "structured": (
        "请将以下 Excel 汇总数据按以下结构化格式输出周报：\n"
        "1. 本周工作概览\n"
        "2. 主要工作进展（按项目分类）\n"
        "3. 关键数据指标\n"
        "4. 问题与解决方案\n"
        "每个部分用编号标题区分，内容使用项目符号。"
    ),
    "bullet": (
        "请将以下 Excel 汇总数据整理为项目符号列表形式的周报。"
        "每个工作项以 '- ' 开头，按工作模块分组，并标注完成情况。"
    ),
}


def build_prompt(excel_text: str, config: Dict[str, Any]) -> str:
    """根据所选格式构建用户提示词。"""
    fmt = config["output_format"]
    if fmt == "custom":
        system_prompt = config["custom_prompt"] or "请基于以下数据生成周报。"
    else:
        system_prompt = FORMAT_TEMPLATES.get(fmt, FORMAT_TEMPLATES["markdown"])

    return (
        f"{system_prompt}\n\n"
        f"以下是本周 Excel 工作数据汇总，请基于此内容生成周报：\n\n"
        f"{excel_text}"
    )


def call_llm_api(prompt: str, config: Dict[str, Any]) -> str:
    """统一调用 LLM API (OpenAI 兼容协议)。

    根据 config["provider"] 选择 minimax / deepseek / opencode / qwen，
    使用对应 provider 的 base_url / model / api_key 进行请求。
    """
    provider_name = config["provider"]
    providers = config.get("providers", {})
    if provider_name not in providers:
        raise ValueError(
            f"未知 provider: {provider_name}，可选: {list(providers.keys())}"
        )

    prov = providers[provider_name]
    api_key = prov.get("api_key", "").strip()
    if not api_key:
        # 列出已配置 api_key 的 provider，方便用户切换
        configured = [
            p for p, cfg in providers.items()
            if cfg.get("api_key", "").strip()
        ]
        hint = ""
        if configured:
            hint = (
                f"\n提示: 以下 provider 已配置 api_key: {configured}\n"
                f"     可使用  python weekly_report.py --provider {configured[0]}  切换"
            )
        raise ValueError(
            f"provider '{provider_name}' 缺少 api_key，请在 config.json 中填入该 provider 的 api_key"
            + hint
        )

    base_url = prov["base_url"]
    model = prov["model"]
    max_tokens_field = prov.get("max_tokens_field", "max_completion_tokens")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一名专业的项目周报撰写助手，擅长从 Excel 工作数据中提炼关键信息，"
                    "生成结构清晰、重点突出、数据准确的中文周报。"
                    "\n\n严格输出要求："
                    "\n1. 直接以周报标题（如 `# 周报`）开头，不要任何对话式前缀、寒暄或解释性语句"
                    "\n2. 禁止输出诸如「好的」「根据您提供的」「为您生成」「以下是为您整理的」等开头语"
                    "\n3. 仅输出周报正文本身，不要附加任何说明"
                    "\n4. 严禁在周报中提及任何数据汇总过程的元信息，例如："
                    "   「来源 Excel 文件数」「原始条目数」「去重后任务条目数」「共 N 条记录」「去重后剩余 N 项」"
                    "   等表述。这些是 Python 处理过程的中间数据，与周报内容无关，不应出现在周报中"
                    "\n5. 周报应聚焦于实际工作内容、项目进展、问题与解决方案，"
                    "不要描述「汇总」「去重」「Excel」「条目」「记录数」等数据处理概念"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens_field: config["tokens_to_generate"],
        "temperature": config["temperature"],
        "stream": False,
    }

    # 思考模式开关（仅当 provider 支持 thinking_param 时生效）
    if config.get("thinking_enabled") and prov.get("thinking_param"):
        payload["thinking"] = prov["thinking_param"]

    print(f"[INFO] 调用 {provider_name} / {model} 生成周报中...")
    if config.get("thinking_enabled"):
        thinking_status = "enabled" if prov.get("thinking_param") else "not supported by this provider"
        print(f"[INFO] 思考模式: {thinking_status}")

    # ============ 发起 HTTP 请求 ============
    # timeout 使用 (connect_timeout, read_timeout) 元组：
    #   - connect_timeout: 建立连接的超时（10 秒足够）
    #   - read_timeout: 读取数据的超时（用 config.timeout，默认 180 秒）
    timeout_tuple = (10, config["timeout"])
    try:
        response = requests.post(
            base_url,
            headers=headers,
            json=payload,
            timeout=timeout_tuple,
        )
    except requests.exceptions.ConnectTimeout:
        raise RuntimeError(
            f"连接超时（10秒未建立连接）。可能原因：网络异常、DNS 解析失败、"
            f"或 base_url 不可达（当前: {base_url}）。请检查网络与配置。"
        )
    except requests.exceptions.ReadTimeout:
        raise RuntimeError(
            f"读取超时（{config['timeout']}秒未返回完整响应）。可能原因："
            f"API 服务响应慢、思考模式生成时间长、或生成内容较长。"
            f"建议：增大 config.json 中的 timeout 值后重试。"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"请求超时（{config['timeout']}秒）。建议：增大 config.json 中的 timeout 值后重试。"
        )
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"网络连接失败：{e}\n可能原因：DNS 解析失败、无网络、防火墙拦截、"
            f"或 base_url 错误（当前: {base_url}）。请检查网络与配置。"
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"HTTP 请求异常: {e}")

    # ============ 解析 HTTP 状态码 ============
    status_code = response.status_code
    if status_code == 401:
        raise RuntimeError(
            f"鉴权失败 (HTTP 401)：api_key 无效或已过期。请检查 config.json 中 "
            f"{provider_name} 的 api_key 是否正确。"
        )
    if status_code == 403:
        raise RuntimeError(
            f"无访问权限 (HTTP 403)：api_key 无权调用该模型，或账户余额不足。"
            f"请前往 {provider_name} 控制台检查权限与额度。"
        )
    if status_code == 404:
        raise RuntimeError(
            f"接口不存在 (HTTP 404)：base_url 或 model 错误。"
            f"请检查 config.json 中 {provider_name} 的 base_url='{base_url}' 与 model='{model}'。"
        )
    if status_code == 429:
        retry_after = response.headers.get("Retry-After", "?")
        raise RuntimeError(
            f"请求频率超限 (HTTP 429)：触发 {provider_name} 限流。"
            f"建议等待 {retry_after} 秒后重试，或降低调用频率。"
        )
    if 500 <= status_code < 600:
        # 安全：不输出响应体到日志（可能含敏感信息），仅提示状态码
        raise RuntimeError(
            f"{provider_name} 服务端异常 (HTTP {status_code})，请稍后重试。"
        )
    if status_code != 200:
        # 安全：不输出响应体到日志（可能含敏感信息），仅提示状态码
        raise RuntimeError(
            f"请求失败 (HTTP {status_code})。"
        )

    # ============ 解析响应体 ============
    try:
        data = response.json()
    except ValueError as e:
        # 安全：不输出响应体到日志（可能含敏感信息）
        raise RuntimeError(
            f"响应不是有效 JSON: {e}"
        )

    # 检查 provider 私有错误字段（如 MiniMax 的 base_resp）
    base_resp = data.get("base_resp") or {}
    if base_resp and base_resp.get("status_code") and base_resp.get("status_code") != 0:
        raise RuntimeError(
            f"{provider_name} API 返回错误: code={base_resp.get('status_code')}, "
            f"msg={base_resp.get('status_msg')}"
        )

    # OpenAI 兼容响应解析
    choices = data.get("choices") or []
    if not choices:
        # 兼容部分 provider 直接返回 error 字段的情况
        err = data.get("error") or {}
        if err:
            raise RuntimeError(
                f"{provider_name} API 返回错误: "
                f"type={err.get('type')}, message={err.get('message')}, code={err.get('code')}"
            )
        # 安全：不输出整个响应体（可能含敏感信息），仅提示字段缺失
        raise RuntimeError(
            f"{provider_name} API 返回无 choices 字段，请检查 model/base_url 配置或 provider 服务状态。"
        )

    message = choices[0].get("message", {})
    content = message.get("content", "")
    if not content:
        # 安全：不输出整个响应体（可能含敏感信息）
        raise RuntimeError(
            f"{provider_name} API 返回 content 为空。"
        )

    # 提取 token 使用情况（OpenAI 兼容协议标准字段）
    usage = data.get("usage") or {}
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", 0)
    # 思考模式相关 token（部分 provider 提供，如 DeepSeek）
    reasoning_tokens = (
        usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
        if usage.get("completion_tokens_details")
        else 0
    )

    print(f"[INFO] Token 使用统计:")
    print(f"       - 输入 Prompt tokens : {prompt_tokens:,}")
    if reasoning_tokens:
        print(f"       - 其中思考 tokens    : {reasoning_tokens:,}")
    print(f"       - 输出 Completion    : {completion_tokens:,}")
    print(f"       - 总计 Total tokens  : {total_tokens:,}")

    # 仅返回周报正文内容，不输出模型的思考过程
    # 同时清理模型可能残留的对话式开头语（如"好的，根据您提供的数据..."）
    return strip_chat_prefix(content)
