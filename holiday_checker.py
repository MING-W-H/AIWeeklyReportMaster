# -*- coding: utf-8 -*-
"""节假日检查模块。

判断今天是否中国法定节假日，用于定时任务执行前的前置校验。
如果是节假日，周报任务应跳过执行。

数据来源（按优先级）：
    1. 本地硬编码的法定节假日规则（国庆、春节等固定日期）
    2. 在线 API：https://timor.tech/api/holiday (免费，免鉴权，HTTPS 防篡改)
    3. 本地缓存：holidays_cache.json (避免每次启动都联网)

如果在线 API 不可用，则回退到本地缓存；若缓存也不可用，则按"非节假日"处理（不阻断执行）。

安全说明：使用 HTTPS 防止中间人篡改节假日数据导致任务被恶意跳过。
"""
import json
import ssl
import urllib.request
import urllib.error
from datetime import datetime, date
from pathlib import Path
from typing import Optional


CACHE_FILE = Path(__file__).parent / "holidays_cache.json"
API_URL = "https://timor.tech/api/holiday/info/$date"


# ============ 本地硬编码的法定节假日（按公历日期） ============
# 用于在线 API 返回异常时的兜底判断。每年更新。
# type=0 工作日, type=1 节假日(法定放假), type=2 调休上班(周末补班), type=3 周末
HARDCODED_HOLIDAYS = {
    # 2026 年法定节假日（具体日期以国务院公告为准，以下为常见安排）
    "2026-01-01": ("元旦", 1),
    "2026-02-15": ("春节", 1), "2026-02-16": ("春节", 1), "2026-02-17": ("春节", 1),
    "2026-02-18": ("春节", 1), "2026-02-19": ("春节", 1), "2026-02-20": ("春节", 1), "2026-02-21": ("春节", 1),
    "2026-04-04": ("清明节", 1), "2026-04-05": ("清明节", 1), "2026-04-06": ("清明节", 1),
    "2026-05-01": ("劳动节", 1), "2026-05-02": ("劳动节", 1), "2026-05-03": ("劳动节", 1),
    "2026-06-19": ("端午节", 1), "2026-06-20": ("端午节", 1), "2026-06-21": ("端午节", 1),
    "2026-09-25": ("中秋节", 1), "2026-09-26": ("中秋节", 1), "2026-09-27": ("中秋节", 1),
    "2026-10-01": ("国庆节", 1), "2026-10-02": ("国庆节", 1), "2026-10-03": ("国庆节", 1),
    "2026-10-04": ("国庆节", 1), "2026-10-05": ("国庆节", 1), "2026-10-06": ("国庆节", 1), "2026-10-07": ("国庆节", 1),
    # 调休上班日（周末补班，不算节假日）
    "2026-02-14": ("春节前调休", 2),
    "2026-02-28": ("春节后调休", 2),
    "2026-04-26": ("劳动节前调休", 2),
    "2026-10-10": ("国庆节后调休", 2),
}

# 调休上班日集合（type=2，这些日期虽然是周末，但需要上班）
HARDCODED_WORKDAYS = {d for d, (n, t) in HARDCODED_HOLIDAYS.items() if t == 2}
# 法定节假日集合（type=1，这些日期放假）
HARDCODED_HOLIDAY_DATES = {d for d, (n, t) in HARDCODED_HOLIDAYS.items() if t == 1}


def _fetch_holiday_info(d: date) -> Optional[dict]:
    """从 timor.tech API 查询某天是否为节假日。

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
    url = API_URL.replace("$date", date_str)
    try:
        # 使用 HTTPS 并强制启用证书校验，防止中间人篡改节假日数据
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        ctx = ssl.create_default_context()  # 默认启用证书校验
        with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("code") == 0:
            return data
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ConnectionError):
        pass
    return None


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def is_holiday(d: Optional[date] = None) -> bool:
    """判断某天是否为节假日（含周末、法定节假日）。

    逻辑：
        1. 若日期在硬编码的调休上班日列表中 -> 返回 False（周末补班，需工作）
        2. 若日期在硬编码的法定节假日列表中 -> 返回 True
        3. 查缓存 / 在线 API
        4. API 不可用时，按周六周日判断

    Args:
        d: 日期，默认今天

    Returns:
        True = 节假日/周末（放假），False = 工作日（含调休上班）
    """
    if d is None:
        d = datetime.now().date()
    date_str = d.strftime("%Y-%m-%d")

    # 1. 硬编码规则优先（调休上班日 -> False）
    if date_str in HARDCODED_WORKDAYS:
        return False
    # 法定节假日 -> True
    if date_str in HARDCODED_HOLIDAY_DATES:
        return True

    # 2. 查缓存
    cache = _load_cache()
    cached = cache.get(date_str)
    if cached is not None:
        return cached.get("is_holiday", False)

    # 3. 查在线 API
    info = _fetch_holiday_info(d)
    if info is not None:
        type_info = info.get("type", {})
        # type=0 工作日, type=1 节假日, type=2 调休上班(周末), type=3 周末
        holiday_flag = type_info.get("type", 0) in (1, 3)
        cache[date_str] = {
            "is_holiday": holiday_flag,
            "name": type_info.get("name", ""),
            "type": type_info.get("type", 0),
            "source": "timor.tech",
        }
        _save_cache(cache)
        return holiday_flag

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
