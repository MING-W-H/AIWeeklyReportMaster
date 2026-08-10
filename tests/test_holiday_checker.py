# -*- coding: utf-8 -*-
"""holiday_checker 的单元测试。

is_holiday 对 2025/2026 年走本地数据文件（holidays_data.json），
不依赖网络，测试可离线运行。
"""
from datetime import date

import holiday_checker
from holiday_checker import is_holiday, should_skip_execution


def test_2026_statutory_holiday_is_holiday():
    # 2026 元旦（法定放假）
    assert is_holiday(date(2026, 1, 1)) is True


def test_2026_makeup_workday_is_not_holiday():
    # 2026-01-04 为周日但调休上班，应视为工作日
    assert is_holiday(date(2026, 1, 4)) is False


def test_2026_chinese_new_year_holiday():
    # 2026 春节假期
    assert is_holiday(date(2026, 2, 16)) is True
    assert is_holiday(date(2026, 2, 14)) is False  # 春节前调休上班


def test_regular_weekend_is_holiday():
    # 2026-07-11 为周六
    assert is_holiday(date(2026, 7, 11)) is True


def test_regular_workday_is_not_holiday():
    # 2026-07-13 为周一（数据文件中未列出的普通日）
    assert is_holiday(date(2026, 7, 13)) is False


def test_2025_data_also_available():
    # 2025-10-01 国庆（放假），2025-10-11 调休上班
    assert is_holiday(date(2025, 10, 1)) is True
    assert is_holiday(date(2025, 10, 11)) is False


def test_should_skip_execution_holiday():
    skip, reason = should_skip_execution(date(2026, 1, 1))
    assert skip is True
    assert "跳过" in reason


def test_should_skip_execution_workday():
    skip, reason = should_skip_execution(date(2026, 7, 13))
    assert skip is False
    assert "正常执行" in reason


def test_data_file_contains_recent_years():
    data = holiday_checker._load_data_file()
    assert "2025" in data and "2026" in data


def test_year_sets_extraction():
    year_data = {
        "2026-01-01": ["元旦", 1],
        "2026-01-04": ["元旦后调休", 2],
    }
    hdays, wdays = holiday_checker._year_sets(year_data)
    assert hdays == {"2026-01-01"}
    assert wdays == {"2026-01-04"}
