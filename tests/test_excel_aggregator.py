# -*- coding: utf-8 -*-
"""excel_aggregator 单元测试。

覆盖场景：
- _column_letter_to_index 列字母 → 索引转换
- _is_invalid_row 无效行过滤（表头 / 汇总行 / 空行 / 纯序号行）
- collect_excel_files 目录扫描与扩展名过滤
- collect_tasks_from_excel 提取 B/D/H 三列并按行合并（含表头匹配与列字母兜底）
- aggregate_excel_content 单文件汇总 + 去重 + 编号列表输出
- max_chars_per_sheet 字符上限截断
"""
import os
from pathlib import Path

import pandas as pd
import pytest

from excel_aggregator import (
    _clean_cell,
    _column_letter_to_index,
    _is_invalid_row,
    aggregate_excel_content,
    collect_excel_files,
    collect_tasks_from_excel,
)


# ============ 测试数据 ============

def _make_excel(path: Path, df: pd.DataFrame) -> Path:
    df.to_excel(path, index=False)
    return path


def _sample_df() -> pd.DataFrame:
    """带标准表头的示例数据：含重复行、汇总行、纯序号行。"""
    return pd.DataFrame({
        "序号": [1, 2, 3, 4, 5],
        "任务名称": ["任务A", "任务B", "任务A", "总计", "12"],
        "所属商机": ["商机1", "商机2", "商机1", "", ""],
        "项目/需求": ["项目X", "项目Y", "项目X", "", ""],
        "合同号": ["HT-1", "HT-2", "HT-1", "", ""],
        "工作描述": ["开发接口", "修复缺陷", "开发接口", "", ""],
    })


# ============ 纯函数辅助 ============

def test_column_letter_to_index():
    assert _column_letter_to_index("A") == 0
    assert _column_letter_to_index("B") == 1
    assert _column_letter_to_index("H") == 7
    assert _column_letter_to_index("Z") == 25
    assert _column_letter_to_index("AA") == 26
    assert _column_letter_to_index("AB") == 27


def test_clean_cell():
    assert _clean_cell(None) == ""
    assert _clean_cell(float("nan")) == ""
    assert _clean_cell("  文本  ") == "文本"
    # 换行压缩：内部空行去掉，非空行保留顺序
    assert _clean_cell("第一行\n\n  第二行  ") == f"第一行{os.linesep}第二行"


def test_is_invalid_row():
    assert _is_invalid_row("", "", "") is True                      # 三列全空
    assert _is_invalid_row("任务名称", "", "") is True               # 表头行
    assert _is_invalid_row("总计", "", "") is True                   # 汇总行
    assert _is_invalid_row("12", "", "") is True                     # 纯序号行
    assert _is_invalid_row("12", "项目X", "") is False               # 有项目内容则有效
    assert _is_invalid_row("任务A", "", "开发") is False              # 正常行


# ============ collect_excel_files ============

def test_collect_excel_files_filters_and_sorts(tmp_path):
    (tmp_path / "b.xlsx").write_bytes(b"x")
    (tmp_path / "a.xls").write_bytes(b"x")
    (tmp_path / "c.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.xlsx").write_bytes(b"x")  # 不递归

    files = collect_excel_files(str(tmp_path), [".xlsx", ".xls"])
    assert files == [tmp_path / "a.xls", tmp_path / "b.xlsx"]


def test_collect_excel_files_missing_folder():
    with pytest.raises(FileNotFoundError):
        collect_excel_files("/nonexistent/path/xyz", [".xlsx"])


# ============ collect_tasks_from_excel ============

def test_collect_tasks_from_excel(tmp_path):
    """按表头匹配三列，跳过汇总行/纯序号行，保留重复行。"""
    path = _make_excel(tmp_path / "tasks.xlsx", _sample_df())
    records = collect_tasks_from_excel(path)
    assert records == [
        "任务A | 项目：项目X | 描述：开发接口",
        "任务B | 项目：项目Y | 描述：修复缺陷",
        "任务A | 项目：项目X | 描述：开发接口",
    ]


def test_collect_tasks_from_excel_letter_fallback(tmp_path):
    """表头不匹配时回退到列字母 B/D/H。"""
    df = pd.DataFrame({
        "c0": [1, 2],
        "c1": ["任务A", "任务B"],
        "c2": ["商机1", "商机2"],
        "c3": ["项目X", "项目Y"],
        "c4": ["HT", "HT"],
        "c5": ["", ""],
        "c6": ["", ""],
        "c7": ["开发", "修复"],
    })
    path = _make_excel(tmp_path / "fallback.xlsx", df)
    records = collect_tasks_from_excel(path)
    assert records == [
        "任务A | 项目：项目X | 描述：开发",
        "任务B | 项目：项目Y | 描述：修复",
    ]


def test_collect_tasks_from_excel_max_chars(tmp_path):
    """超过 max_chars_per_sheet 后停止追加该 Sheet 剩余行。"""
    path = _make_excel(tmp_path / "tasks.xlsx", _sample_df())
    # 第一条记录约 22 字符：30 字符上限只放得下第一条
    records = collect_tasks_from_excel(path, max_chars_per_sheet=30)
    assert records == ["任务A | 项目：项目X | 描述：开发接口"]

    # 上限小于第一条记录长度时直接截断为空
    records = collect_tasks_from_excel(path, max_chars_per_sheet=5)
    assert records == []


# ============ aggregate_excel_content ============

def test_aggregate_excel_content_dedup_and_numbered(tmp_path):
    """单文件汇总：去重 + 编号列表，汇总行/纯序号行不进入结果。"""
    config = {
        "excel_folder": str(tmp_path),
        "excel_extensions": [".xlsx"],
        "max_chars_per_sheet": 30000,
    }
    path = _make_excel(tmp_path / "tasks.xlsx", _sample_df())
    result = aggregate_excel_content(config, excel_file=path)
    assert result == (
        "以下为本 Excel 中 B 列任务名称、D 列项目/需求、H 列工作描述的去重汇总列表：\n"
        "\n"
        "1. 任务A | 项目：项目X | 描述：开发接口\n"
        "2. 任务B | 项目：项目Y | 描述：修复缺陷"
    )


def test_aggregate_excel_content_missing_file(tmp_path):
    config = {
        "excel_folder": str(tmp_path),
        "excel_extensions": [".xlsx"],
        "max_chars_per_sheet": 30000,
    }
    with pytest.raises(FileNotFoundError):
        aggregate_excel_content(config, excel_file=tmp_path / "missing.xlsx")


def test_aggregate_excel_content_picks_latest_file(tmp_path):
    """未指定 excel_file 时，取文件夹中最新修改的文件。"""
    config = {
        "excel_folder": str(tmp_path),
        "excel_extensions": [".xlsx"],
        "max_chars_per_sheet": 30000,
    }
    older_df = pd.DataFrame({
        "序号": [1],
        "任务名称": ["旧任务"],
        "所属商机": [""],
        "项目/需求": [""],
        "合同号": [""],
        "工作描述": ["旧描述"],
    })
    older = _make_excel(tmp_path / "older.xlsx", older_df)
    newer = _make_excel(tmp_path / "newer.xlsx", _sample_df())

    # 显式把 older 的修改时间改早，避免文件系统时间精度导致的不确定性
    old_mtime = newer.stat().st_mtime - 120
    os.utime(older, (old_mtime, old_mtime))

    result = aggregate_excel_content(config)
    assert "旧任务" not in result
    assert "任务A" in result
