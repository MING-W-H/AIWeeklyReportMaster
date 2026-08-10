# -*- coding: utf-8 -*-
"""output_resolver.calc_last_week_range 单元测试。

覆盖场景：
- 周一 / 周中 / 周日：上周范围固定为上一个自然周（周一到周日）
- 日期格式无前导零（2026.7.6 而非 2026.07.06）
- 同年范围省略结束年份（2026.7.6-7.12）
- 跨年范围保留完整年份（2025.12.29-2026.1.4）
"""
from datetime import datetime

from output_resolver import calc_last_week_range


def _expect(date_str, start, end, range_str, full):
    return {
        "date": date_str,
        "last_week_start": start,
        "last_week_end": end,
        "last_week_range": range_str,
        "last_week_full": full,
    }


def test_monday():
    """周一：上周为上一个自然周。"""
    today = datetime(2026, 7, 13)  # 周一
    assert calc_last_week_range(today) == _expect(
        "2026.7.13", "2026.7.6", "2026.7.12",
        "2026.7.6-7.12", "2026.7.6-2026.7.12",
    )


def test_mid_week_wednesday():
    """周中：与周一结果一致。"""
    today = datetime(2026, 7, 15)  # 周三
    assert calc_last_week_range(today) == _expect(
        "2026.7.15", "2026.7.6", "2026.7.12",
        "2026.7.6-7.12", "2026.7.6-2026.7.12",
    )


def test_sunday():
    """周日：上周仍在当周之前，范围不包含今天。"""
    today = datetime(2026, 7, 19)  # 周日
    assert calc_last_week_range(today) == _expect(
        "2026.7.19", "2026.7.6", "2026.7.12",
        "2026.7.6-7.12", "2026.7.6-2026.7.12",
    )


def test_single_digit_month_day_no_leading_zero():
    """月份/日期为个位数时不补前导零。"""
    today = datetime(2026, 7, 3)  # 周五
    assert calc_last_week_range(today) == _expect(
        "2026.7.3", "2026.6.22", "2026.6.28",
        "2026.6.22-6.28", "2026.6.22-2026.6.28",
    )


def test_cross_year_range_keeps_full_year():
    """跨年：上周一在上一年、上周日在今年，范围带完整年份。"""
    today = datetime(2026, 1, 5)  # 周一，上周跨年
    assert calc_last_week_range(today) == _expect(
        "2026.1.5", "2025.12.29", "2026.1.4",
        "2025.12.29-2026.1.4", "2025.12.29-2026.1.4",
    )


def test_january_first_same_year_last_week():
    """1 月 1 日：上周完全位于去年，同年范围省略结束年份。"""
    today = datetime(2026, 1, 1)  # 周四
    assert calc_last_week_range(today) == _expect(
        "2026.1.1", "2025.12.22", "2025.12.28",
        "2025.12.22-12.28", "2025.12.22-2025.12.28",
    )
