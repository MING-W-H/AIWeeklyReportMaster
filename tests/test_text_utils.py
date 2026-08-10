# -*- coding: utf-8 -*-
"""text_utils.strip_chat_prefix 单元测试。

覆盖场景：
- 空文本原样返回
- 多份周报（草稿 + 思考独白 + 正式版）→ 以最后一个顶层标题为起点
- 单份周报带对话式前缀 → 删除前缀
- 无顶层标题但有二级标题 → 保留标题起的内容
- 无任何标题 → 正则清理常见开头语
"""
from text_utils import strip_chat_prefix


def test_empty_text():
    assert strip_chat_prefix("") == ""
    assert strip_chat_prefix(None) is None


def test_multiple_reports_keeps_last_top_level_title():
    """草稿 + 思考独白 + 正式版：取最后一个顶层标题为真正起点。"""
    text = (
        "# 草稿周报\n"
        "初步内容\n"
        "\n"
        "（思考中）好的，下面是正式版：\n"
        "\n"
        "# Vue 本周周报\n"
        "正式内容\n"
    )
    assert strip_chat_prefix(text) == "# Vue 本周周报\n正式内容"


def test_dialogue_prefix_before_single_title():
    """单份周报：删除标题之前的对话式开头。"""
    text = "好的，根据您提供的数据，为您生成本周周报：\n\n# 周报\n内容"
    assert strip_chat_prefix(text) == "# 周报\n内容"


def test_second_level_title_without_top_level():
    """无顶层标题但有 ## 二级标题：保留标题起的内容。"""
    text = "以下是周报：\n\n## 本周总结\n内容"
    assert strip_chat_prefix(text) == "## 本周总结\n内容"


def test_no_title_common_prefix():
    """无标题：正则清理「为您生成...」式开头语。"""
    text = "为您生成本周周报。\n本周完成 5 项任务。"
    assert strip_chat_prefix(text) == "本周完成 5 项任务。"


def test_no_title_short_prefix():
    """无标题：正则清理「好的，」式开头语。"""
    text = "好的，本周内容如下：\n1. 任务"
    assert strip_chat_prefix(text) == "本周内容如下：\n1. 任务"


def test_no_title_no_prefix_unchanged():
    """无标题且无常见前缀：原样返回。"""
    text = "本周工作内容：\n- 完成 A\n- 完成 B"
    assert strip_chat_prefix(text) == text


def test_leading_blank_lines_stripped():
    """清理后去除开头的多余空行。"""
    text = "\n\n# 周报\n内容"
    assert strip_chat_prefix(text) == "# 周报\n内容"
