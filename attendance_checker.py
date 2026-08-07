# -*- coding: utf-8 -*-
"""独立考勤查询脚本（钉钉考勤接口）。

通过钉钉开放平台「查询企业考勤数据权限」接口，查询指定用户
在指定日期范围内的考勤打卡结果（上班/下班，含实际打卡时间），
输出明细表格与汇总。

使用方式：
    1. 按 userId 查询（推荐，最多一次 50 人）：
       python attendance_checker.py --userids T0265,T0266,T0267
       python attendance_checker.py --userids T0265 --start 2026-07-27 --end 2026-08-02

    2. 按部门查询（查询部门下全部成员，需通讯录读权限）：
       python attendance_checker.py --dept 872611

    3. 默认用户：未指定 --userids / --dept 时，使用 config.json
       attendance.user_ids 配置的名单（未配置时回退到 dingtalk 接收人/审核人）

    4. 导出 Excel：
       python attendance_checker.py --excel            # 保存到 attendance.output_folder（默认 attendance_output/）
       python attendance_checker.py --excel a.xlsx     # 保存到指定路径
       导出文件夹含员工考勤隐私数据，已在 .gitignore 中忽略

日期范围默认最近 7 天（含今天）。查询时间段可通过：
        - 命令行 --start/--end（优先级最高）
        - config.json attendance.start_date/end_date（留空则用默认）

    接口单次最多查询 7 天，脚本会自动将更长的时间范围拆分为多段请求。
    接口返回的记录包含实际打卡时间（userCheckTime），表格单元格显示
    「打卡结果 打卡时间」（如：正常 09:02 / 迟到 09:15）。
    Excel 明细除打卡结果/时间外，还包含打卡位置（范围内/范围外）与
    打卡来源（用户打卡/考勤机/自动打卡等）。

权限要求：
- 查询企业考勤数据权限（必填，钉钉开发者后台 → 权限管理）
- 成员信息读权限（可选，用于把 userId 显示为姓名）
- 通讯录部门信息读权限（仅 --dept 模式需要）

凭证：环境变量 DINGTALK_APP_KEY / DINGTALK_APP_SECRET > config.json
dingtalk.app_key / app_secret（与项目内其他钉钉脚本一致）。
"""
import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import requests

from config_manager import load_config
from retry_utils import retry_request

# ============ 钉钉开放平台接口 ============
_GETTOKEN_URL = "https://oapi.dingtalk.com/gettoken"
_GETSIMPLE_LIST_URL = "https://oapi.dingtalk.com/attendance/list"
_GET_USER_URL = "https://oapi.dingtalk.com/topapi/v2/user/get"
_LIST_USER_URL = "https://oapi.dingtalk.com/topapi/v2/user/list"

# 单次接口最多查询 7 天（含首尾）
_MAX_DAYS_PER_REQUEST = 7
# 单次接口最多 50 个 userId / 50 条记录
_MAX_USERS_PER_REQUEST = 50
_PAGE_SIZE = 50

# 打卡结果码 → 中文（attendance/list 接口的 timeResult 取值）
CHECK_RESULT_MAP = {
    "Normal": "正常",
    "Late": "迟到",
    "SeriousLate": "严重迟到",
    "Absenteeism": "旷工",
    "Early": "早退",
    "NotSigned": "未打卡",
}
# 打卡位置结果码 → 中文（attendance/list 接口的 locationResult 取值）
LOCATION_RESULT_MAP = {
    "Normal": "范围内",
    "Outside": "范围外",
    "NotSigned": "未打卡",
}
# 打卡来源码 → 中文（attendance/list 接口的 sourceType 取值）
SOURCE_TYPE_MAP = {
    "USER": "用户打卡",
    "ATM": "考勤机",
    "APPROVE": "审批系统",
    "SYSTEM": "考勤系统",
    "AUTO_CHECK": "自动打卡",
    "BOSS": "老板改签",
    "BEACON": "Beacon",
    "DING_ATM": "钉钉考勤机",
}
# ============ 凭证与 token ============
def _get_credentials(config: Dict[str, Any]) -> Tuple[str, str]:
    """读取钉钉应用凭证：环境变量 > config.json。"""
    import os

    dt_cfg = config.get("dingtalk", {})
    app_key = (os.getenv("DINGTALK_APP_KEY") or dt_cfg.get("app_key", "")).strip()
    app_secret = (os.getenv("DINGTALK_APP_SECRET") or dt_cfg.get("app_secret", "")).strip()
    if not app_key or not app_secret:
        raise RuntimeError(
            "钉钉凭证未配置：请在 .env 中设置 DINGTALK_APP_KEY / DINGTALK_APP_SECRET，"
            "或在 config.json 的 dingtalk.app_key / app_secret 中填入"
        )
    return app_key, app_secret


def _get_oapi_token(app_key: str, app_secret: str) -> str:
    """获取旧版 oapi access_token（考勤接口使用该端点）。"""
    resp = retry_request(
        requests.get,
        _GETTOKEN_URL,
        params={"appkey": app_key, "appsecret": app_secret},
        timeout=15,
        max_retries=2,
        base_delay=1.0,
        backoff=2.0,
        func_name="钉钉 oapi access_token 获取",
    )
    data = resp.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"获取钉钉 access_token 失败: {data.get('errmsg', data)}")
    return data.get("access_token", "")


# ============ 用户解析 ============
def _resolve_names(token: str, user_ids: List[str]) -> Dict[str, str]:
    """尽力把 userId 解析为姓名（权限不足时回退为 userId）。"""
    names: Dict[str, str] = {}
    for uid in user_ids:
        try:
            resp = retry_request(
                requests.post,
                _GET_USER_URL,
                params={"access_token": token},
                json={"userid": uid},
                timeout=15,
                max_retries=1,
                base_delay=1.0,
                backoff=2.0,
                func_name="钉钉用户信息查询",
            )
            data = resp.json()
            if data.get("errcode") == 0:
                names[uid] = (data.get("result") or {}).get("name", "") or ""
        except Exception:
            pass
    return names


def _list_dept_members(token: str, dept_id: int) -> List[Dict[str, str]]:
    """列出指定部门下的成员（name + userid）。需已开通通讯录读权限。"""
    members: List[Dict[str, str]] = []
    cursor = 0
    while True:
        resp = retry_request(
            requests.post,
            _LIST_USER_URL,
            params={"access_token": token},
            json={"dept_id": dept_id, "cursor": cursor, "size": 100},
            timeout=15,
            max_retries=2,
            base_delay=1.0,
            backoff=2.0,
            func_name="钉钉部门成员列表查询",
        )
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError(
                f"钉钉成员列表查询失败: {data.get('errmsg', data)}。"
                "--dept 模式需要「通讯录部门信息读权限」和「成员信息读权限」"
            )
        result = data.get("result", {})
        for user in result.get("list", []):
            members.append({
                "name": user.get("name", ""),
                "userid": user.get("userid", ""),
            })
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor", 0)
    return members


# ============ 考勤查询 ============
def _chunk_date_ranges(start: datetime, end: datetime,
                       chunk_days: int = _MAX_DAYS_PER_REQUEST
                       ) -> List[Tuple[datetime, datetime]]:
    """把 [start, end] 拆分为不超过 chunk_days 天（含首尾）的子区间。"""
    chunks: List[Tuple[datetime, datetime]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def _fetch_attendance(token: str, user_ids: List[str],
                      start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """分页 + 分段查询考勤打卡结果，返回原始记录列表。"""
    records: List[Dict[str, Any]] = []
    for cs, ce in _chunk_date_ranges(start, end):
        offset = 0
        while True:
            payload = {
                "workDateFrom": cs.strftime("%Y-%m-%d %H:%M:%S"),
                "workDateTo": ce.strftime("%Y-%m-%d %H:%M:%S"),
                "userIdList": user_ids,
                "offset": offset,
                "limit": _PAGE_SIZE,
                "isI18n": False,
            }
            resp = retry_request(
                requests.post,
                _GETSIMPLE_LIST_URL,
                params={"access_token": token},
                json=payload,
                timeout=20,
                max_retries=2,
                base_delay=1.0,
                backoff=2.0,
                func_name="钉钉考勤记录查询",
            )
            data = resp.json()
            if data.get("errcode") != 0:
                errmsg = data.get("errmsg", str(data))
                if "权限" in errmsg or "60011" in str(data.get("errcode")):
                    raise RuntimeError(
                        f"考勤查询失败: {errmsg}。请在钉钉开发者后台「权限管理」中"
                        f"申请「查询企业考勤数据权限」后重试"
                    )
                raise RuntimeError(f"考勤查询失败: {errmsg}")
            records.extend(data.get("recordresult") or [])
            if not data.get("hasMore"):
                break
            offset += _PAGE_SIZE
    return records


def _build_matrix(records: List[Dict[str, Any]],
                  user_ids: List[str]) -> Dict[str, Dict[str, Dict[str, Dict[str, str]]]]:
    """构建 matrix[userId][date][recordType] = {result, time, location, source}。"""
    matrix: Dict[str, Dict[str, Dict[str, Dict[str, str]]]] = {}
    for uid in user_ids:
        matrix.setdefault(uid, {})
    for r in records:
        uid = r.get("userId", "")
        work_date = _ms_to_date(r.get("workDate"))
        rec_type = r.get("checkType", "")
        item = {
            "result": r.get("timeResult", "") or "",
            "time": _ms_to_hhmm(r.get("userCheckTime")),
            "location": r.get("locationResult", "") or "",
            "source": r.get("sourceType", "") or "",
        }
        if uid in matrix and work_date:
            matrix[uid].setdefault(work_date, {})[rec_type] = item
    return matrix


def _ms_to_date(ms) -> str:
    """把钉钉接口返回的毫秒时间戳转为 YYYY-MM-DD（兼容已是字符串的情况）。"""
    if not ms:
        return ""
    if isinstance(ms, str) and "-" in ms:
        return ms[:10]
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return str(ms)


def _ms_to_hhmm(ms) -> str:
    """把钉钉接口返回的毫秒时间戳转为 HH:MM（实际打卡时间，兼容字符串）。"""
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%H:%M")
    except (ValueError, OSError, OverflowError):
        return str(ms)


# ============ 输出 ============
def _fmt_cell(day: Dict[str, Dict[str, str]]) -> str:
    """把一天的上下班结果格式化为「上班/下班」（带实际打卡时间）。"""
    def _side(item: Dict[str, str]) -> str:
        if not item:
            return ""
        result = item.get("result", "") or ""
        cn = CHECK_RESULT_MAP.get(result, result)
        t = item.get("time", "") or ""
        return f"{cn} {t}" if t else cn

    on = _side(day.get("OnDuty") or {})
    off = _side(day.get("OffDuty") or {})
    if not on and not off:
        return "—"
    if not on:
        return f"-/{off}"
    if not off:
        return f"{on}/-"
    return f"{on}/{off}"


def _print_report(matrix: Dict[str, Dict[str, Dict[str, str]]],
                  user_ids: List[str], names: Dict[str, str],
                  start: datetime, end: datetime,
                  all_records: List[Dict[str, Any]]) -> None:
    """控制台输出矩阵明细表 + 汇总。"""
    day_list = _date_list(start, end)
    day_strs = [d.strftime("%m-%d") for d in day_list]

    # 表头
    header = "用户" + " " * 4
    cells_width = max(len(_fmt_cell(matrix.get(uid, {}).get(day_list[i].strftime("%Y-%m-%d"), {}))) for uid in user_ids for i in range(len(day_list))) if user_ids else 0
    col_w = max(9, cells_width)
    for ds in day_strs:
        header += f"{ds:^{col_w}}"
    print("=" * len(header))
    print(f"钉钉考勤查询结果（{start:%Y-%m-%d} ~ {end:%Y-%m-%d}）")
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    for uid in user_ids:
        name = names.get(uid, "")
        label = f"{name}({uid})" if name else uid
        row = f"{label:<12}"
        for d in day_list:
            cell = _fmt_cell(matrix.get(uid, {}).get(d.strftime("%Y-%m-%d"), {}))
            row += f"{cell:^{col_w}}"
        print(row)

    # 汇总
    print("-" * len(header))
    print("汇总（各结果出现次数，含上班+下班卡）：")
    for uid in user_ids:
        name = names.get(uid, "")
        label = f"{name}({uid})" if name else uid
        cnt = Counter(r.get("timeResult", "") for r in all_records if r.get("userId") == uid)
        parts = []
        for code, cn in CHECK_RESULT_MAP.items():
            n = cnt.get(code, 0)
            if n:
                parts.append(f"{cn}{n}")
        if not parts:
            parts.append("无打卡记录")
        print(f"  {label:<20} {'，'.join(parts)}")


def _date_list(start: datetime, end: datetime) -> List[datetime]:
    days: List[datetime] = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _export_excel(path: str, matrix: Dict[str, Dict[str, Dict[str, str]]],
                  user_ids: List[str], names: Dict[str, str],
                  start: datetime, end: datetime,
                  all_records: List[Dict[str, Any]]) -> None:
    """导出明细到 Excel（依赖 pandas + openpyxl，项目 requirements 已包含）。"""
    try:
        import pandas as pd
    except ImportError:
        raise RuntimeError("导出 Excel 需要 pandas，请先执行: pip install pandas openpyxl")

    day_list = _date_list(start, end)
    rows = []
    for uid in user_ids:
        name = names.get(uid, "")
        for d in day_list:
            day = matrix.get(uid, {}).get(d.strftime("%Y-%m-%d"), {})
            on = day.get("OnDuty") or {}
            off = day.get("OffDuty") or {}
            rows.append({
                "用户ID": uid,
                "姓名": name,
                "日期": d.strftime("%Y-%m-%d"),
                "星期": "一二三四五六日"[d.weekday()],
                "上班结果": CHECK_RESULT_MAP.get(on.get("result", ""), ""),
                "上班时间": on.get("time", ""),
                "上班位置": LOCATION_RESULT_MAP.get(on.get("location", ""), on.get("location", "")),
                "上班来源": SOURCE_TYPE_MAP.get(on.get("source", ""), on.get("source", "")),
                "下班结果": CHECK_RESULT_MAP.get(off.get("result", ""), ""),
                "下班时间": off.get("time", ""),
                "下班位置": LOCATION_RESULT_MAP.get(off.get("location", ""), off.get("location", "")),
                "下班来源": SOURCE_TYPE_MAP.get(off.get("source", ""), off.get("source", "")),
            })
    detail_df = pd.DataFrame(rows)

    summary_rows = []
    for uid in user_ids:
        name = names.get(uid, "")
        cnt = Counter(r.get("timeResult", "") for r in all_records if r.get("userId") == uid)
        summary_rows.append({
            "用户ID": uid,
            "姓名": name,
            **{CHECK_RESULT_MAP[code]: cnt.get(code, 0) for code in CHECK_RESULT_MAP},
        })
    summary_df = pd.DataFrame(summary_rows)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        detail_df.to_excel(writer, sheet_name="明细", index=False)
        summary_df.to_excel(writer, sheet_name="汇总", index=False)
    print(f"[INFO] 已导出 Excel: {path}")


# ============ 主流程 ============
def main() -> int:
    parser = argparse.ArgumentParser(
        description="钉钉考勤查询工具：查询指定用户指定日期范围内的考勤打卡结果",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python attendance_checker.py --userids T0265,T0266\n"
            "  python attendance_checker.py --userids T0265 --start 2026-07-27 --end 2026-08-02\n"
            "  python attendance_checker.py --dept 872611\n"
            "  python attendance_checker.py --excel\n"
            "  python attendance_checker.py --excel attendance.xlsx"
        ),
    )
    parser.add_argument("--userids", help="员工 userId 列表，逗号分隔，最多 50 人")
    parser.add_argument("--dept", type=int, help="部门 ID，查询部门下全部成员")
    parser.add_argument("--start", help="开始日期 YYYY-MM-DD（默认 config attendance.start_date，再默认最近 7 天）")
    parser.add_argument("--end", help="结束日期 YYYY-MM-DD（默认 config attendance.end_date，再默认今天）")
    parser.add_argument("--excel", nargs="?", const="__auto__", metavar="PATH",
                        help="导出 Excel：指定路径，或省略路径默认保存到 "
                             "config.json attendance.output_folder（含考勤隐私数据，已 gitignore）")
    args = parser.parse_args()

    # 加载配置与凭证
    config = load_config()
    try:
        app_key, app_secret = _get_credentials(config)
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return 1

    # 日期范围：--start/--end > config.json attendance.start_date/end_date > 默认最近 7 天
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    att_cfg = config.get("attendance", {})

    def _parse_date(s: str, name: str) -> datetime:
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            print(f"[ERROR] {name} 格式应为 YYYY-MM-DD")
            raise SystemExit(1)

    end = today
    if args.end:
        end = _parse_date(args.end, "--end")
    elif (att_cfg.get("end_date") or "").strip():
        end = _parse_date(att_cfg["end_date"], "attendance.end_date")

    start = None
    if args.start:
        start = _parse_date(args.start, "--start")
    elif (att_cfg.get("start_date") or "").strip():
        start = _parse_date(att_cfg["start_date"], "attendance.start_date")
    if start is None:
        start = end - timedelta(days=6)
    if start > end:
        print("[ERROR] 开始日期不能晚于结束日期")
        return 1

    print("[INFO] 正在获取钉钉 access_token ...")
    token = _get_oapi_token(app_key, app_secret)

    # 确定用户列表
    if args.dept:
        print(f"[INFO] 正在查询部门 {args.dept} 的成员 ...")
        members = _list_dept_members(token, args.dept)
        if not members:
            print(f"[WARN] 部门 {args.dept} 下未查询到成员")
            return 0
        user_ids = [m["userid"] for m in members]
        names = {m["userid"]: m["name"] for m in members}
        print(f"[INFO] 部门 {args.dept} 共 {len(user_ids)} 名成员")
    elif args.userids:
        user_ids = [u.strip() for u in args.userids.split(",") if u.strip()]
        if len(user_ids) > _MAX_USERS_PER_REQUEST:
            print(f"[ERROR] 单次最多查询 {_MAX_USERS_PER_REQUEST} 人")
            return 1
        names = _resolve_names(token, user_ids)
        found = [u for u in user_ids if names.get(u)]
        if found:
            print(f"[INFO] 已解析 {len(found)}/{len(user_ids)} 个 userId 的姓名")
    else:
        att_cfg = config.get("attendance", {})
        dt_cfg = config.get("dingtalk", {})
        user_ids = [
            str(s).strip() for s in (att_cfg.get("user_ids") or []) if str(s).strip()
        ]
        if not user_ids:
            # 兼容旧配置：未配置 attendance.user_ids 时回退到钉钉接收人/审核人
            user_ids = [
                str(s).strip()
                for s in (dt_cfg.get("recipient_staff_ids") or []) + (dt_cfg.get("approver_staff_ids") or [])
                if str(s).strip()
            ]
            user_ids = list(dict.fromkeys(user_ids))  # 去重保序
        if not user_ids:
            print("[ERROR] 未指定用户：请使用 --userids 或 --dept，"
                  "或在 config.json 的 attendance.user_ids 中配置")
            return 1
        names = _resolve_names(token, user_ids)
        print(f"[INFO] 使用 config.json attendance.user_ids 名单，共 {len(user_ids)} 人")

    # 查询考勤
    print(f"[INFO] 正在查询考勤 {start:%Y-%m-%d} ~ {end:%Y-%m-%d} ...")
    records = _fetch_attendance(token, user_ids, start, end)
    matrix = _build_matrix(records, user_ids)
    print(f"[INFO] 共获取 {len(records)} 条打卡记录")

    # 输出
    _print_report(matrix, user_ids, names, start, end, records)
    if args.excel is not None:
        if args.excel == "__auto__":
            output_folder = config.get("attendance", {}).get("output_folder", "attendance_output")
            os.makedirs(output_folder, exist_ok=True)
            excel_path = os.path.join(
                output_folder, f"考勤_{start:%Y%m%d}-{end:%Y%m%d}.xlsx"
            )
            print(f"[INFO] 未指定 --excel 路径，导出到配置文件夹: {output_folder}")
        else:
            excel_path = args.excel
        _export_excel(excel_path, matrix, user_ids, names, start, end, records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
