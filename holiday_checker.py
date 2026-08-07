# -*- coding: utf-8 -*-
"""节假日检查模块。

判断某天是否为中国法定节假日（含周末、调休上班日），供定时任务前置校验使用。
节假日/周末 → 跳过执行；调休上班日（周末补班）→ 正常执行。

数据按「年份」组织，任意年份均可判断（而非只支持某一年）：

    1. 本地硬编码（最高优先级兜底）：官方公告已发布年份的完整安排
       - 2025 年：《国务院办公厅关于2025年部分节假日安排的通知》(国办发明电〔2024〕12号)
       - 2026 年：《国务院办公厅关于2026年部分节假日安排的通知》(国办发明电〔2025〕7号)
       每年国务院发布新通知后追加对应年份即可
    2. 在线整年 API：https://timor.tech/api/holiday/year/{year}
       一次拉取整年节假日/调休日（免费、免鉴权、HTTPS），覆盖所有年份
    3. 本地缓存：holidays_cache.json（按年缓存，避免每次启动联网）
    4. 单日 API 兜底：https://timor.tech/api/holiday/info/{date}（整年数据获取失败时）
    5. 最终兜底：按周六/周日判断（不阻断执行）

安全说明：使用 HTTPS 并强制启用证书校验，防止中间人篡改节假日数据导致任务被恶意跳过。
"""
import json
import socket
import ssl
import urllib.request
import urllib.error
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Optional, Set, Tuple


CACHE_FILE = Path(__file__).parent / "holidays_cache.json"
# 整年节假日数据（返回当年所有节假日与调休上班日）
API_YEAR_URL = "https://timor.tech/api/holiday/year/$year"
# 单日节假日数据（整年数据获取失败时的兜底）
API_DAY_URL = "https://timor.tech/api/holiday/info/$date"


# ============ 本地硬编码的法定节假日（按年份组织） ============
# 结构：{年份: {日期(YYYY-MM-DD): (节日名, type)}}
# type=0 工作日, type=1 节假日(法定放假), type=2 调休上班(周末补班), type=3 周末
# 每年国务院发布放假通知后，在对应年份下追加该年安排即可。
HARDCODED_HOLIDAYS: Dict[str, Dict[str, Tuple[str, int]]] = {
    # ---- 2025 年：国办发明电〔2024〕12号 ----
    "2025": {
        # 元旦：1月1日(周三)放假1天，不调休
        "2025-01-01": ("元旦", 1),
        # 春节：1月28日(除夕)-2月4日，共8天；1月26日(周日)、2月8日(周六)上班
        "2025-01-28": ("春节", 1), "2025-01-29": ("春节", 1), "2025-01-30": ("春节", 1),
        "2025-01-31": ("春节", 1), "2025-02-01": ("春节", 1), "2025-02-02": ("春节", 1),
        "2025-02-03": ("春节", 1), "2025-02-04": ("春节", 1),
        "2025-01-26": ("春节前调休", 2), "2025-02-08": ("春节后调休", 2),
        # 清明节：4月4日(周五)-6日(周日)，共3天
        "2025-04-04": ("清明节", 1), "2025-04-05": ("清明节", 1), "2025-04-06": ("清明节", 1),
        # 劳动节：5月1日(周四)-5日(周一)，共5天；4月27日(周日)上班
        "2025-05-01": ("劳动节", 1), "2025-05-02": ("劳动节", 1), "2025-05-03": ("劳动节", 1),
        "2025-05-04": ("劳动节", 1), "2025-05-05": ("劳动节", 1),
        "2025-04-27": ("劳动节前调休", 2),
        # 端午节：5月31日(周六)-6月2日(周一)，共3天
        "2025-05-31": ("端午节", 1), "2025-06-01": ("端午节", 1), "2025-06-02": ("端午节", 1),
        # 国庆节、中秋节：10月1日(周三)-8日(周三)，共8天；9月28日(周日)、10月11日(周六)上班
        "2025-10-01": ("国庆节", 1), "2025-10-02": ("国庆节", 1), "2025-10-03": ("国庆节", 1),
        "2025-10-04": ("国庆节", 1), "2025-10-05": ("国庆节", 1), "2025-10-06": ("国庆节", 1),
        "2025-10-07": ("国庆节", 1), "2025-10-08": ("国庆节", 1),
        "2025-09-28": ("国庆节前调休", 2), "2025-10-11": ("国庆节后调休", 2),
    },
    # ---- 2026 年：国办发明电〔2025〕7号 ----
    "2026": {
        # 元旦：1月1日(周四)-3日(周六)，共3天；1月4日(周日)上班
        "2026-01-01": ("元旦", 1), "2026-01-02": ("元旦", 1), "2026-01-03": ("元旦", 1),
        "2026-01-04": ("元旦后调休", 2),
        # 春节：2月15日(周日)-23日(周一)，共9天；2月14日(周六)、2月28日(周六)上班
        "2026-02-15": ("春节", 1), "2026-02-16": ("春节", 1), "2026-02-17": ("春节", 1),
        "2026-02-18": ("春节", 1), "2026-02-19": ("春节", 1), "2026-02-20": ("春节", 1),
        "2026-02-21": ("春节", 1), "2026-02-22": ("春节", 1), "2026-02-23": ("春节", 1),
        "2026-02-14": ("春节前调休", 2), "2026-02-28": ("春节后调休", 2),
        # 清明节：4月4日(周六)-6日(周一)，共3天
        "2026-04-04": ("清明节", 1), "2026-04-05": ("清明节", 1), "2026-04-06": ("清明节", 1),
        # 劳动节：5月1日(周五)-5日(周二)，共5天；5月9日(周六)上班
        "2026-05-01": ("劳动节", 1), "2026-05-02": ("劳动节", 1), "2026-05-03": ("劳动节", 1),
        "2026-05-04": ("劳动节", 1), "2026-05-05": ("劳动节", 1),
        "2026-05-09": ("劳动节后调休", 2),
        # 端午节：6月19日(周五)-21日(周日)，共3天
        "2026-06-19": ("端午节", 1), "2026-06-20": ("端午节", 1), "2026-06-21": ("端午节", 1),
        # 中秋节：9月25日(周五)-27日(周日)，共3天
        "2026-09-25": ("中秋节", 1), "2026-09-26": ("中秋节", 1), "2026-09-27": ("中秋节", 1),
        # 国庆节：10月1日(周四)-7日(周三)，共7天；9月20日(周日)、10月10日(周六)上班
        "2026-10-01": ("国庆节", 1), "2026-10-02": ("国庆节", 1), "2026-10-03": ("国庆节", 1),
        "2026-10-04": ("国庆节", 1), "2026-10-05": ("国庆节", 1), "2026-10-06": ("国庆节", 1), "2026-10-07": ("国庆节", 1),
        "2026-09-20": ("国庆节前调休", 2), "2026-10-10": ("国庆节后调休", 2),
    },
}


def _hardcoded_year_sets(year: str) -> Tuple[Set[str], Set[str]]:
    """返回某年硬编码的 (法定节假日集合, 调休上班集合)。"""
    hdays: Set[str] = set()
    wdays: Set[str] = set()
    for date_str, (name, type_no) in HARDCODED_HOLIDAYS.get(year, {}).items():
        if type_no == 1:
            hdays.add(date_str)
        elif type_no == 2:
            wdays.add(date_str)
    return hdays, wdays


def _fetch_year_holidays(year: int) -> Optional[Dict[str, bool]]:
    """从 timor.tech API 获取某年全部节假日/调休日。

    返回：{日期(YYYY-MM-DD): True=放假, False=调休上班}，不含普通工作日/周末。
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
        result: Dict[str, bool] = {}
        for date_key, item in holiday_map.items():
            if isinstance(item, dict) and "holiday" in item:
                # API 的 key 为 MM-DD 格式，完整日期在每项的 date 字段中
                date_str = item.get("date") or date_key
                if len(str(date_str)) == 10 and str(date_str)[4] == "-":
                    result[str(date_str)] = bool(item["holiday"])
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


def _load_cache() -> dict:
    """加载按年份组织的本地缓存 {年份: {日期: 是否放假}}。

    旧版缓存为单日 key（YYYY-MM-DD -> dict），与新格式不兼容，
    检测到旧格式时视为空缓存（整年数据会在下次查询时重新拉取）。
    """
    if not CACHE_FILE.exists():
        return {}
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(cache, dict):
        return {}
    for key in cache:
        if len(key) == 10 and key[4] == "-":
            return {}
    return cache


def _save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _year_holiday_map(year: int) -> Optional[Dict[str, bool]]:
    """获取某年的节假日映射 {日期(YYYY-MM-DD): 是否放假}（不含普通工作日/周末）。

    优先级：本地缓存 → 在线整年 API（成功后写入缓存）。
    返回 None 表示该年数据不可得。
    """
    cache = _load_cache()
    year_key = str(year)
    cached = cache.get(year_key)
    if isinstance(cached, dict) and cached:
        # 防御：旧版本可能缓存了 MM-DD 格式的键，校验后丢弃重建
        if all(len(str(k)) == 10 and str(k)[4] == "-" for k in cached):
            return cached

    year_map = _fetch_year_holidays(year)
    if year_map is not None:
        cache[year_key] = year_map
        _save_cache(cache)
        return year_map
    return None


def is_holiday(d: Optional[date] = None) -> bool:
    """判断某天是否为节假日（含周末、法定节假日）。

    逻辑（按年份匹配，任意年份均适用）：
        1. 当年硬编码规则（调休上班日 -> False；法定节假日 -> True）
        2. 该年整年数据（本地缓存 → 在线 API），未列出的日期按普通日处理（周末除外）
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

    # 1. 当年硬编码规则优先
    hdays, wdays = _hardcoded_year_sets(str(d.year))
    if date_str in wdays:
        return False
    if date_str in hdays:
        return True

    # 2. 该年整年数据（缓存 / 在线 API）
    year_map = _year_holiday_map(d.year)
    if year_map is not None:
        if date_str in year_map:
            return year_map[date_str]
        # 该年数据中未列出的日期为普通日：仅周六/周日放假
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
