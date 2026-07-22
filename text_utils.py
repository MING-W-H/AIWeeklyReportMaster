# -*- coding: utf-8 -*-
"""文本处理模块。

负责：
- strip_chat_prefix: 移除 LLM 输出中的对话式前缀、思考过程泄露和重复输出
- markdown_to_html: 将 Markdown 文本简单转换为 HTML（用于邮件正文）
"""
import re
from typing import List


def strip_chat_prefix(text: str) -> str:
    """移除 LLM 输出中的对话式前缀、思考过程泄露和重复输出。

    策略：
    1. 若文本中包含多份以顶层标题（# 周报 等）开头的周报（模型有时会先输出一份草稿，
       再夹杂"思考独白"，然后输出正式版），取最后一个顶层标题作为真正起点。
    2. 若只有一份周报，删除标题之前的对话式开头（"好的，根据..."等）。
    3. 若完全没有标题，使用正则清理常见开头语。
    """
    if not text:
        return text

    lines = text.splitlines()

    # 找出所有顶层标题（# 开头，单#，非 ##）的行索引
    # 这些可能是模型多次输出周报的起点
    top_level_title_indices = [
        i for i, line in enumerate(lines)
        if line.strip().startswith("# ") and not line.strip().startswith("## ")
    ]

    if top_level_title_indices:
        # 取最后一个顶层标题作为真正的周报起点
        # 这样可以丢弃：对话前缀 + 草稿周报 + 思考独白 + 正式周报前的所有内容
        start_idx = top_level_title_indices[-1]
        cleaned_lines = lines[start_idx:]
        return "\n".join(cleaned_lines).lstrip("\n")

    # 没有顶层标题，但有 ## 二级标题的情况
    any_title_indices = [
        i for i, line in enumerate(lines)
        if line.strip().startswith("#")
    ]
    if any_title_indices:
        start_idx = any_title_indices[-1]
        return "\n".join(lines[start_idx:]).lstrip("\n")

    # 完全没有标题，使用正则清理常见开头语
    pattern = re.compile(
        r"^(好的[，,。]?|根据(您|你)提供的[^。]*。[，,]?\s*|为您生成[^。]*。[，,]?\s*|以下是为您[^。]*。[，,]?\s*)",
        re.MULTILINE,
    )
    cleaned = pattern.sub("", text, count=1)
    return cleaned.lstrip("\n")


def markdown_to_html(md_text: str) -> str:
    """将 Markdown 文本简单转换为 HTML（用于邮件正文）。

    仅做基础转换：标题、列表、表格、加粗、代码块。
    不依赖第三方库，保持轻量。
    """
    lines = md_text.splitlines()
    html_parts: List[str] = []
    in_table = False
    in_code = False

    for line in lines:
        stripped = line.strip()

        # 代码块
        if stripped.startswith("```"):
            if in_code:
                html_parts.append("</code></pre>")
                in_code = False
            else:
                html_parts.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            html_parts.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "\n")
            continue

        # 空行
        if not stripped:
            if in_table:
                html_parts.append("</tbody></table>")
                in_table = False
            html_parts.append("")
            continue

        # 表格行
        if "|" in stripped and stripped.startswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if not in_table:
                html_parts.append('<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">')
                html_parts.append("<thead><tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr></thead>")
                html_parts.append("<tbody>")
                in_table = True
            elif all(set(c.strip()) <= set("- :") for c in cells):
                # 分隔行（如 |---|---|），跳过
                continue
            else:
                html_parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            continue

        if in_table:
            html_parts.append("</tbody></table>")
            in_table = False

        # 标题
        if stripped.startswith("### "):
            html_parts.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            html_parts.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            html_parts.append(f"<h1>{stripped[2:]}</h1>")
        # 列表
        elif stripped.startswith("- "):
            html_parts.append(f"<li>{stripped[2:]}</li>")
        else:
            # 加粗 **text** → <strong>text</strong>
            bolded = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
            html_parts.append(f"<p>{bolded}</p>")

    if in_table:
        html_parts.append("</tbody></table>")
    if in_code:
        html_parts.append("</code></pre>")

    body = "\n".join(html_parts)
    return (
        '<div style="font-family: Microsoft YaHei, Arial, sans-serif; '
        'font-size: 14px; line-height: 1.8; color: #333;">'
        f"{body}</div>"
    )
