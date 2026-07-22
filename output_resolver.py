# -*- coding: utf-8 -*-
"""输出路径解析模块。

负责根据配置解析周报输出文件路径，支持日期占位符：
    {date}              → 当前日期 (如 2026.7.20)
    {last_week_start}   → 上一周周一日期 (如 2026.7.13)
    {last_week_end}     → 上一周周日日期 (如 2026.7.19)
    {last_week_range}   → 上一周日期范围 (如 2026.7.13-7.19)
    {last_week_full}    → 上一周日期范围带年份 (如 2026.7.13-2026.7.19)
"""
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict


def _fmt_no_leading_zero(dt: datetime) -> str:
    """格式化日期为 YYYY.M.D（去掉月份和日期的前导零）。
    跨平台兼容: Windows 不支持 strftime 的 %-m / %-d，统一用正则去前导零。
    """
    return re.sub(
        r"^(\d+)\.0*(\d+)\.0*(\d+)$",
        r"\1.\2.\3",
        dt.strftime("%Y.%m.%d"),
    )


def calc_last_week_range(today: datetime) -> Dict[str, str]:
    """计算上一周的日期范围信息。

    返回包含 5 个键的字典：
        date             : 当前日期
        last_week_start  : 上一周周一
        last_week_end    : 上一周周日
        last_week_range  : 日期范围（同年省略结束年份）
        last_week_full   : 日期范围（带完整年份）
    """
    today_weekday = today.weekday()  # 周一=0, 周日=6
    # 若今天是周一(0)，则上周一 = today - 7天，上周日 = today - 1天
    # 若今天是周三(2)，则上周一 = today - (2+7)天，上周日 = today - (2+1)天
    last_monday = today - timedelta(days=today_weekday + 7)
    last_sunday = today - timedelta(days=today_weekday + 1)

    date_str = _fmt_no_leading_zero(today)
    last_week_start = _fmt_no_leading_zero(last_monday)
    last_week_end = _fmt_no_leading_zero(last_sunday)

    # 范围格式：同年省略年份，不同年保留完整
    if last_monday.year == last_sunday.year:
        # 同年：2026.7.13-7.19
        end_no_year = re.sub(r"^(\d+)\.(\d+\.\d+)$", r"\2", last_week_end)
        last_week_range = f"{last_week_start}-{end_no_year}"
    else:
        # 跨年：2025.12.29-2026.1.4
        last_week_range = f"{last_week_start}-{last_week_end}"

    last_week_full = f"{last_week_start}-{last_week_end}"

    return {
        "date": date_str,
        "last_week_start": last_week_start,
        "last_week_end": last_week_end,
        "last_week_range": last_week_range,
        "last_week_full": last_week_full,
    }


def resolve_output_path(config: Dict[str, Any]) -> Path:
    """根据配置解析输出文件路径。"""
    fmt = config["output_format"]
    if config["output_file"]:
        return Path(config["output_file"])

    template = config.get("output_file_template") or "Vue{date}周报"

    today = datetime.now()
    date_info = calc_last_week_range(today)

    # 替换占位符（先替换长占位符，避免 {last_week_start} 被 {last_week} 误匹配）
    file_name = template
    file_name = file_name.replace("{last_week_full}", date_info["last_week_full"])
    file_name = file_name.replace("{last_week_range}", date_info["last_week_range"])
    file_name = file_name.replace("{last_week_end}", date_info["last_week_end"])
    file_name = file_name.replace("{last_week_start}", date_info["last_week_start"])
    file_name = file_name.replace("{date}", date_info["date"])

    ext = ".md" if fmt == "markdown" else ".txt"
    if not file_name.lower().endswith((".md", ".txt", ".markdown")):
        file_name = file_name + ext
    output_folder = config.get("output_folder", "reports")
    out_dir = Path(output_folder)
    # 相对路径时，基于脚本所在目录解析
    if not out_dir.is_absolute():
        out_dir = Path(__file__).parent / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / file_name
