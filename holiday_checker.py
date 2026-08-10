# -*- coding: utf-8 -*-
"""节假日检查模块。

判断某天是否为中国法定节假日（含周末、调休上班日），供定时任务前置校验使用。
节假日/周末 → 跳过执行；调休上班日（周末补班）→ 正常执行。

数据按「年份」组织，任意年份均可判断（而非只支持某一年）。为降低数据维护成本，
节假日数据与代码分离，统一保存在本地数据文件 holidays_data.json：

    1. 本地数据文件（最高优先级兜底，离线可用）：holidays_data.json
       - 结构：{年份: {日期(YYYY-MM-DD): [节日名, type]}}
       - type=1 法定放假, type=2 调休上班(周末补班)
       - 内容来源：官方公告数据（初始由内置种子写入）+ 在线 API 自动写回
       - 每年国务院发布通知后，改该 JSON 文件即可，无需改代码；
         也可以运行「python holiday_checker.py --update」自动从在线 API 刷新
    2. 在线整年 API：https://timor.tech/api/holiday/year/{year}
       一次拉取整年节假日/调休日（免费、免鉴权、HTTPS），覆盖所有年份。
       拉取成功后自动写回本地数据文件 —— 即使 API 后续停服，最近一次
       成功拉取的整年数据仍保存在本地可用（解决「API 停服退化为只看周末」）
    3. 单日 API 兜底：https://timor.tech/api/holiday/info/{date}（整年数据获取失败时）
    4. 最终兜底：按周六/周日判断（不阻断执行）

内置种子数据（SEED_HOLIDAYS）仅在数据文件缺失/损坏时用于重建，日常以文件为准。

安全说明：使用 HTTPS 并强制启用证书校验，防止中间人篡改节假日数据导致任务被恶意跳过。
"""
import argparse
import json
import socket
import ssl
import urllib.request
import urllib.error
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from logger import get_logger

logger = get_logger(__name__)

# 本地数据文件：官方公告数据 + 在线 API 写回数据的持久化存储
DATA_FILE = Path(__file__).parent / "holidays_data.json"
# 整年节假日数据（返回当年所有节假日与调休上班日）
API_YEAR_URL = "https://timor.tech/api/holiday/year/$year"
# 单日节假日数据（整年数据获取失败时的兜底）
API_DAY_URL = "https://timor.tech/api/holiday/info/$date"


# ============ 内置种子数据（离线引导） ============
# 结构：{年份: {日期(YYYY-MM-DD): (节日名, type)}}
# type=1 节假日(法定放假), type=2 调休上班(周末补班)
# 仅用于 holidays_data.json 缺失/损坏时重建；日常更新请直接编辑该 JSON 文件，
# 或运行「python holiday_checker.py --update」从在线 API 刷新。
SEED_HOLIDAYS: Dict[str, Dict[str, Tuple[str, int]]] = {
    # ---- 2025 年：国办发明电〔2024〕12号 ----
    "2025": {
        "2025-01-01": ("元旦", 1),
        "2025-01-28": ("春节", 1), "2025-01-29": ("春节", 1), "2025-01-30": ("春节", 1),
        "2025-01-31": ("春节", 1), "2025-02-01": ("春节", 1), "2025-02-02": ("春节", 1),
        "2025-02-03": ("春节", 1), "2025-02-04": ("春节", 1),
        "2025-01-26": ("春节前调休", 2), "2025-02-08": ("春节后调休", 2),
        "2025-04-04": ("清明节", 1), "2025-04-05": ("清明节", 1), "2025-04-06": ("清明节", 1),
        "2025-05-01": ("劳动节", 1), "2025-05-02": ("劳动节", 1), "2025-05-03": ("劳动节", 1),
        "2025-05-04": ("劳动节", 1), "2025-05-05": ("劳动节", 1),
        "2025-04-27": ("劳动节前调休", 2),
        "2025-05-31": ("端午节", 1), "2025-06-01": ("端午节", 1), "2025-06-02": ("端午节", 1),
        "2025-10-01": ("国庆节", 1), "2025-10-02": ("国庆节", 1), "2025-10-03": ("国庆节", 1),
        "2025-10-04": ("国庆节", 1), "2025-10-05": ("国庆节", 1), "2025-10-06": ("国庆节", 1),
        "2025-10-07": ("国庆节", 1), "2025-10-08": ("国庆节", 1),
        "2025-09-28": ("国庆节前调休", 2), "2025-10-11": ("国庆节后调休", 2),
    },
    # ---- 2026 年：国办发明电〔2025〕7号 ----
    "2026": {
        "2026-01-01": ("元旦", 1), "2026-01-02": ("元旦", 1), "2026-01-03": ("元旦", 1),
        "2026-01-04": ("元旦后调休", 2),
        "2026-02-15": ("春节", 1), "2026-02-16": ("春节", 1), "2026-02-17": ("春节", 1),
        "2026-02-18": ("春节", 1), "2026-02-19": ("春节", 1), "2026-02-20": ("春节", 1),
        "2026-02-21": ("春节", 1), "2026-02-22": ("春节", 1), "2026-02-23": ("春节", 1),
        "2026-02-14": ("春节前调休", 2), "2026-02-28": ("春节后调休", 2),
        "2026-04-04": ("清明节", 1), "2026-04-05": ("清明节", 1), "2026-04-06": ("清明节", 1),
        "2026-05-01": ("劳动节", 1), "2026-05-02": ("劳动节", 1), "2026-05-03": ("劳动节", 1),
        "2026-05-04": ("劳动节", 1), "2026-05-05": ("劳动节", 1),
        "2026-05-09": ("劳动节后调休", 2),
        "2026-06-19": ("端午节", 1), "2026-06-20": ("端午节", 1), "2026-06-21": ("端午节", 1),
        "2026-09-25": ("中秋节", 1), "2026-09-26": ("中秋节", 1), "2026-09-27": ("中秋节", 1),
        "2026-10-01": ("国庆节", 1), "2026-10-02": ("国庆节", 1), "2026-10-03": ("国庆节", 1),
        "2026-10-04": ("国庆节", 1), "2026-10-05": ("国庆节", 1), "2026-10-06": ("国庆节", 1),
        "2026-10-07": ("国庆节", 1),
        "2026-09-20": ("国庆节前调休", 2), "2026-10-10": ("国庆节后调休", 2),
    },
}


def _load_data_file() -> Dict[str, Dict[str, List[Any]]]:
    """加载本地数据文件 holidays_data.json。

    返回 {年份: {日期(YYYY-MM-DD): [节日名, type]}}。
    文件缺失/损坏时用内置种子重建并写回（首次运行自动生成）。
    """
    if not DATA_FILE.exists():
        data = {y: {ds: list(v) for ds, v in year.items()}
                for y, year in SEED_HOLIDAYS.items()}
        _save_data_file(data)
        return data
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("节假日数据文件 %s 损坏，使用内置种子重建", DATA_FILE.name)
        data = {y: {ds: list(v) for ds, v in year.items()}
                for y, year in SEED_HOLIDAYS.items()}
        _save_data_file(data)
        return data
    if not isinstance(data, dict):
        return {y: {ds: list(v) for ds, v in year.items()}
                for y, year in SEED_HOLIDAYS.items()}
    return data


def _save_data_file(data: Dict[str, Any]) -> None:
    """原子写入数据文件（先写临时文件再替换，避免进程中断损坏数据）。"""
    tmp = DATA_FILE.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(DATA_FILE)
    except OSError:
        logger.warning("节假日数据文件 %s 写入失败（只读目录或磁盘错误）", DATA_FILE.name)


def _year_sets(year_data: Dict[str, List[Any]]) -> Tuple[Set[str], Set[str]]:
    """从某年的数据条目提取 (法定节假日集合, 调休上班集合)。"""
    hdays: Set[str] = set()
    wdays: Set[str] = set()
    for date_str, item in year_data.items():
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        type_no = item[1]
        if type_no == 1:
            hdays.add(date_str)
        elif type_no == 2:
            wdays.add(date_str)
    return hdays, wdays


def _fetch_year_holidays(year: int) -> Optional[Dict[str, Tuple[str, int]]]:
    """从 timor.tech API 获取某年全部节假日/调休日。

    返回：{日期(YYYY-MM-DD): (节日名, type)}，type=1 放假, type=2 调休上班。
    失败时返回 None。
    """
    url = API_YEAR_URL.replace("$year", str(year))
    try:
        # 使用 HTTPS 并强制启用证书校验，防止中间人篡改节假日数据
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        ctx = ssl.create_default_context()  # 默认启用证书校验
        with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") != 0:
            return None
        holiday_map = data.get("holiday")
        if not isinstance(holiday_map, dict):
            return None
        result: Dict[str, Tuple[str, int]] = {}
        for date_key, item in holiday_map.items():
            if isinstance(item, dict) and "holiday" in item:
                # API 的 key 为 MM-DD 格式，完整日期在每项的 date 字段中
                date_str = item.get("date") or date_key
                if len(str(date_str)) == 10 and str(date_str)[4] == "-":
                    name = str(item.get("name") or "节假日")
                    type_no = 1 if item["holiday"] else 2
                    result[str(date_str)] = (name, type_no)
        return result if result else None
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ConnectionError,
            ssl.SSLError, socket.timeout, OSError):
        return None


def _fetch_day_info(d: date) -> Optional[dict]:
    """从 timor.tech API 查询某天是否为节假日（单日兜底）。

    返回格式：
        {
            "code": 0,
            "type": {"type": 0|1|2|3, "name": "...", "week": "..."}
        }
    type 含义：
        0 = 工作日
        1 = 节假日（法定放假）
        2 = 调休上班（周末补班）
        3 = 周末
    """
    date_str = d.strftime("%Y-%m-%d")
    url = API_DAY_URL.replace("$date", date_str)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") == 0:
            return data
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ConnectionError,
            ssl.SSLError, socket.timeout, OSError):
        pass
    return None


def is_holiday(d: Optional[date] = None) -> bool:
    """判断某天是否为节假日（含周末、法定节假日）。

    逻辑（按年份匹配，任意年份均适用）：
        1. 本地数据文件（内置种子 / 在线 API 写回），调休上班日 -> False；法定节假日 -> True
        2. 在线整年 API（数据文件缺失该年时），成功后写回数据文件
        3. 单日 API 兜底（整年数据获取失败时）
        4. 最终兜底：周六/周日 = 节假日

    Args:
        d: 日期，默认今天

    Returns:
        True = 节假日/周末（放假），False = 工作日（含调休上班）
    """
    if d is None:
        d = datetime.now().date()
    date_str = d.strftime("%Y-%m-%d")
    data = _load_data_file()

    # 1. 本地数据文件优先（离线可用，无需联网）
    year_data = data.get(str(d.year))
    if isinstance(year_data, dict) and year_data:
        hdays, wdays = _year_sets(year_data)
        if date_str in wdays:
            return False
        if date_str in hdays:
            return True
        # 该年数据完整时，未列出的日期为普通日：仅周六/周日放假
        return d.weekday() >= 5

    # 2. 在线整年 API（成功后写回数据文件，后续离线可用）
    year_map = _fetch_year_holidays(d.year)
    if year_map is not None:
        data[str(d.year)] = {ds: list(v) for ds, v in year_map.items()}
        _save_data_file(data)
        if date_str in year_map:
            return year_map[date_str][1] == 1
        return d.weekday() >= 5

    # 3. 单日 API 兜底（整年数据获取失败时）
    info = _fetch_day_info(d)
    if info is not None:
        # type=0 工作日, type=1 节假日, type=2 调休上班, type=3 周末
        return info.get("type", {}).get("type", 0) in (1, 3)

    # 4. API 不可用时，用简单规则判断：周六/周日 = 节假日
    return d.weekday() >= 5


def should_skip_execution(d: Optional[date] = None) -> tuple[bool, str]:
    """判断定时任务今天是否应跳过执行。

    Returns:
        (should_skip, reason)
        should_skip=True 表示今天是节假日/周末，应跳过
        should_skip=False 表示今天是工作日，应正常执行
    """
    if d is None:
        d = datetime.now().date()
    if is_holiday(d):
        return True, f"今天是节假日或周末 ({d.strftime('%Y-%m-%d')})，跳过执行"
    return False, f"今天是工作日 ({d.strftime('%Y-%m-%d')})，正常执行"


def update_data_file() -> int:
    """从在线 API 刷新本地数据文件（当年 + 次年，调休安排通常提前一年公布）。

    Returns:
        成功更新的年份数量
    """
    data = _load_data_file()
    this_year = datetime.now().year
    updated = 0
    for y in (this_year, this_year + 1):
        year_map = _fetch_year_holidays(y)
        if year_map is None:
            logger.warning("刷新 %d 年数据失败（网络不可用或 API 未更新）", y)
            continue
        data[str(y)] = {ds: list(v) for ds, v in year_map.items()}
        updated += 1
    if updated:
        _save_data_file(data)
        logger.info("节假日数据已刷新 %d 个年份，保存到 %s", updated, DATA_FILE.name)
    else:
        logger.error("节假日数据刷新失败，请检查网络连接或稍后重试")
    return updated


def _print_year_holidays(year: int) -> None:
    """打印某年节假日安排，便于人工核对。"""
    data = _load_data_file()
    year_data = data.get(str(year))
    if not year_data:
        logger.warning("本地数据文件没有 %d 年数据，可运行 --update 从在线 API 拉取", year)
        return
    logger.info("=" * 40)
    logger.info("%d 年节假日安排（数据文件 %s）", year, DATA_FILE.name)
    logger.info("=" * 40)
    for date_str in sorted(year_data):
        name, type_no = year_data[date_str]
        kind = "放假" if type_no == 1 else "调休上班"
        logger.info("  %s  %s（%s）", date_str, name, kind)


def main() -> int:
    """节假日数据维护入口：--update 在线刷新数据文件，--show 查看安排。"""
    parser = argparse.ArgumentParser(
        description="节假日数据维护工具（数据文件: holidays_data.json）"
    )
    parser.add_argument(
        "--update", action="store_true",
        help="从在线 API 刷新本地节假日数据文件（当年 + 次年）",
    )
    parser.add_argument(
        "--show", nargs="?", const=None, type=int, metavar="YEAR",
        help="打印指定年份的节假日安排（默认当年）",
    )
    args = parser.parse_args()

    if args.update:
        return 0 if update_data_file() > 0 else 1

    year = args.show if args.show is not None else datetime.now().year
    _print_year_holidays(year)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
