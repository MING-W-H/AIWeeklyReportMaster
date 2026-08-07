# -*- coding: utf-8 -*-
"""Excel 汇总模块。

负责：
- 处理 CRM 下载的单个 Excel 文件（不再扫描目录、不做跨文件合并）
- 从该 Excel 中提取 B 列「任务名称」、D 列「项目/需求」、H 列「工作描述」
- 将三列内容按行合并为一条记录，单文件内去重
- 输出编号列表格式的汇总文本

适配 CRM 下载的 Excel 列结构：
    A 列：序号
    B 列：任务名称
    C 列：所属商机
    D 列：项目/需求
    E 列：合同号
    F 列：开始时间
    G 列：结束时间
    H 列：工作描述
    I 列：实际工时
    ...
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ============ 列定义 ============
# CRM 下载的 Excel 列结构：
#   A=序号  B=任务名称  C=所属商机  D=项目/需求  E=合同号
#   F=开始时间  G=结束时间  H=工作描述  I=实际工时  ...
# 需要提取的列：B(任务名称)、D(项目/需求)、H(工作描述)
TARGET_COLUMNS: List[Tuple[str, str]] = [
    ("B", "任务名称"),
    ("D", "项目/需求"),
    ("H", "工作描述"),
]

# 跳过的汇总行关键词
SUMMARY_KEYWORDS = ("总计", "合计", "小计", "汇总")

# 跳过的表头关键词（避免把列名本身当作数据）
HEADER_KEYWORDS = ("任务名称", "项目/需求", "工作描述", "项目/需求任务", "序号")


def collect_excel_files(folder: str, extensions: List[str]) -> List[Path]:
    """扫描文件夹下所有 Excel 文件（不递归子目录）。"""
    # 支持相对路径（基于脚本所在目录解析）
    if folder and not os.path.isabs(folder):
        folder = str(Path(__file__).parent / folder)
    if not folder or not os.path.isdir(folder):
        raise FileNotFoundError(f"Excel 文件夹不存在或未配置: {folder}")

    files: List[Path] = []
    for name in os.listdir(folder):
        path = Path(folder) / name
        if path.is_file() and path.suffix.lower() in extensions:
            files.append(path)
    files.sort(key=lambda p: p.name.lower())
    return files


def _column_letter_to_index(letter: str) -> int:
    """将 Excel 列字母（A/B/.../Z/AA/...）转换为 0-based 索引。"""
    idx = 0
    for ch in letter.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _resolve_column_by_letter(df: "pd.DataFrame", letter: str) -> Optional[str]:
    """按列字母（如 'B'）从 DataFrame 中取出对应列名。

    若列数不足则返回 None。
    """
    idx = _column_letter_to_index(letter)
    cols = list(df.columns)
    if idx < len(cols):
        return cols[idx]
    return None


# 列名映射：目标表头 → 兜底列字母
_COLUMN_HEADER_MAP = {
    "任务名称": "B",
    "项目/需求": "D",
    "工作描述": "H",
}


def _resolve_columns_by_header(df: "pd.DataFrame") -> Dict[str, Optional[str]]:
    """优先按表头名匹配列，失败时回退到列字母。

    遍历 DataFrame 的实际列名，尝试匹配目标表头（如"任务名称"）。
    若所有目标列都匹配成功，返回表头匹配结果；
    否则对有匹配失败的列回退到列字母兜底。

    Returns:
        {目标表头: 列名或 None}
    """
    col_names = [str(c).strip() for c in df.columns]
    result: Dict[str, Optional[str]] = {}

    for target, fallback_letter in _COLUMN_HEADER_MAP.items():
        # 尝试按表头名匹配（包含关系匹配）
        matched = None
        for col_name in col_names:
            if target in col_name:
                matched = col_name
                break
        if matched:
            result[target] = matched
        else:
            # 回退到列字母
            result[target] = _resolve_column_by_letter(df, fallback_letter)
            if result[target]:
                print(f"  [DEBUG] 表头「{target}」未匹配，回退到列字母 {fallback_letter}")
    return result


def _clean_cell(value: Any) -> str:
    """清理单元格值：去除 NaN、首尾空白、换行符压缩。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    # 压缩内部多余换行和空白，便于去重和 AI 阅读
    text = os.linesep.join(line.strip() for line in text.splitlines() if line.strip())
    return text


def _is_invalid_row(task_name: str, project: str, description: str) -> bool:
    """判断该行是否为无效行（表头、汇总行、空行、纯序号行）。"""
    # 三列全空
    if not task_name and not project and not description:
        return True
    # 表头行：任务名称列就是"任务名称"等表头关键字
    if task_name in HEADER_KEYWORDS:
        return True
    # 纯汇总行
    if task_name in SUMMARY_KEYWORDS:
        return True
    # 任务名称为纯数字序号（且其他列也空）
    if task_name.isdigit() and not project and not description:
        return True
    return False


def collect_tasks_from_excel(file_path: Path,
                             max_chars_per_sheet: Optional[int] = None) -> List[str]:
    """从单个 Excel 文件中提取 B/D/H 三列并按行合并为记录列表。

    每行合并格式：「任务名称 | 项目/需求 | 工作描述」
    - 若某列为空则跳过该部分
    - 自动跳过表头、空值、汇总行、纯序号行
    - 保留原始顺序
    - max_chars_per_sheet 为正数时，单个 Sheet 汇总文本达到该上限后停止追加（防止超 token）
    """
    try:
        xls = pd.ExcelFile(
            file_path,
            engine="openpyxl" if file_path.suffix.lower() == ".xlsx" else None,
        )
    except Exception:
        try:
            xls = pd.ExcelFile(file_path)
        except Exception as e2:
            hint = ""
            if file_path.suffix.lower() == ".xls":
                hint = "（读取 .xls 需要 xlrd 库，请执行: pip install xlrd>=2.0.1）"
            print(f"  [WARN] 读取失败 {file_path.name}: {e2} {hint}")
            return []

    records: List[str] = []
    for sheet_name in xls.sheet_names:
        try:
            df = xls.parse(sheet_name, header=0)
        except Exception as e:
            print(f"  [WARN] Sheet '{sheet_name}' 读取失败: {e}")
            continue

        if df.empty or df.shape[1] == 0:
            continue

        # 按表头名匹配三列（优先）；失败时回退到列字母
        resolved = _resolve_columns_by_header(df)
        col_b = resolved.get("任务名称")  # 任务名称
        col_d = resolved.get("项目/需求")  # 项目/需求
        col_h = resolved.get("工作描述")  # 工作描述

        if col_b is None:
            print(f"  [WARN] {file_path.name} Sheet '{sheet_name}' 列数不足，无法定位 B 列")
            continue

        series_b = df[col_b]
        series_d = df[col_d] if col_d else None
        series_h = df[col_h] if col_h else None

        sheet_chars = 0
        for i in range(len(df)):
            task_name = _clean_cell(series_b.iloc[i])
            project = _clean_cell(series_d.iloc[i]) if series_d is not None else ""
            description = _clean_cell(series_h.iloc[i]) if series_h is not None else ""

            if _is_invalid_row(task_name, project, description):
                continue

            # 合并三列为一条记录，空列跳过
            parts: List[str] = []
            if task_name:
                parts.append(task_name)
            if project:
                parts.append(f"项目：{project}")
            if description:
                parts.append(f"描述：{description}")
            if not parts:
                continue
            record = " | ".join(parts)

            # 单 Sheet 汇总文本长度上限（防止超 token）
            if max_chars_per_sheet and sheet_chars + len(record) > max_chars_per_sheet:
                print(f"  [WARN] Sheet '{sheet_name}' 汇总文本已达上限 "
                      f"{max_chars_per_sheet} 字符，该 Sheet 剩余行已截断")
                break
            sheet_chars += len(record)
            records.append(record)

    return records


def aggregate_excel_content(config: Dict[str, Any],
                            excel_file: Optional[Path] = None) -> str:
    """汇总单个 Excel 文件的 B/D/H 三列内容（不做跨文件合并）。

    Args:
        config: 全局配置字典
        excel_file: 指定要处理的 Excel 文件路径（CRM 下载的文件）。
            未指定时（--no-crm 或 CRM 未启用），从 excel_folder 目录中
            取最新修改的一个 Excel 文件。

    流程：
        Python 读取该 Excel → 提取 B(任务名称)/D(项目/需求)/H(工作描述) 三列
        → 按行合并 → 单文件内去重 → 交由 AI 优化。
    """
    # 优先使用传入的单个文件（CRM 下载结果）；否则从目录取最新文件兜底
    if excel_file is not None:
        path = Path(excel_file)
        if not path.is_file():
            raise FileNotFoundError(f"Excel 文件不存在: {path}")
        files: List[Path] = [path]
    else:
        files = collect_excel_files(config["excel_folder"], config["excel_extensions"])
        if not files:
            raise FileNotFoundError(
                f"文件夹 {config['excel_folder']} 下未找到 Excel 文件 (扩展名: {config['excel_extensions']})"
            )
        # 只取最新修改的一个文件，不做多文件合并
        files = [max(files, key=lambda p: p.stat().st_mtime)]

    print(f"[INFO] 处理 Excel 文件: {files[0].name}")

    max_chars = config.get("max_chars_per_sheet", 30000)
    records = collect_tasks_from_excel(files[0], max_chars_per_sheet=max_chars)
    # 单文件内去重（保留首次出现的顺序）
    seen = set()
    unique_tasks: List[str] = []
    for record in records:
        if record not in seen:
            seen.add(record)
            unique_tasks.append(record)

    print(f"[INFO] B/D/H 三列合并记录原始条目数: {len(records)}，去重后剩余: {len(unique_tasks)}")

    # 注意：以下过程性元信息仅用于 Python 端控制台日志，不写入汇总文本
    # 以免 AI 在周报中引用"来源文件数/条目数/去重后条目数"等数据汇总过程信息
    lines: List[str] = []
    lines.append("以下为本 Excel 中 B 列任务名称、D 列项目/需求、H 列工作描述的去重汇总列表：")
    lines.append("")
    for idx, task in enumerate(unique_tasks, start=1):
        lines.append(f"{idx}. {task}")

    full_text = "\n".join(lines)
    print(f"[INFO] Excel 汇总完成，接下来交由 AI 优化...")
    return full_text
