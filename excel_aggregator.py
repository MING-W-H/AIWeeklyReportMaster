# -*- coding: utf-8 -*-
"""Excel 汇总模块。

负责：
- 扫描文件夹下所有 Excel 文件
- 从每个 Excel 文件中提取 B 列「任务名称」、D 列「项目/需求」、H 列「工作描述」
- 将三列内容按行合并为一条记录，跨文件去重
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


def collect_tasks_from_excel(file_path: Path) -> List[str]:
    """从单个 Excel 文件中提取 B/D/H 三列并按行合并为记录列表。

    每行合并格式：「任务名称 | 项目/需求 | 工作描述」
    - 若某列为空则跳过该部分
    - 自动跳过表头、空值、汇总行、纯序号行
    - 保留原始顺序
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
            print(f"  [WARN] 读取失败 {file_path.name}: {e2}")
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

        # 按列字母定位三列
        col_b = _resolve_column_by_letter(df, "B")  # 任务名称
        col_d = _resolve_column_by_letter(df, "D")  # 项目/需求
        col_h = _resolve_column_by_letter(df, "H")  # 工作描述

        if col_b is None:
            print(f"  [WARN] {file_path.name} Sheet '{sheet_name}' 列数不足，无法定位 B 列")
            continue

        series_b = df[col_b]
        series_d = df[col_d] if col_d else None
        series_h = df[col_h] if col_h else None

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
            records.append(" | ".join(parts))

    return records


def aggregate_excel_content(config: Dict[str, Any]) -> str:
    """汇总文件夹下所有 Excel 文件的 B/D/H 三列内容。

    流程：
        Python 读取所有 Excel → 提取 B(任务名称)/D(项目/需求)/H(工作描述) 三列
        → 按行合并 → 跨文件去重 → 交由 AI 优化。
    """
    files = collect_excel_files(config["excel_folder"], config["excel_extensions"])
    if not files:
        raise FileNotFoundError(
            f"文件夹 {config['excel_folder']} 下未找到 Excel 文件 (扩展名: {config['excel_extensions']})"
        )

    print(f"[INFO] 共发现 {len(files)} 个 Excel 文件:")
    for f in files:
        print(f"  - {f.name}")

    seen = set()
    unique_tasks: List[str] = []
    total_raw = 0
    for f in files:
        records = collect_tasks_from_excel(f)
        total_raw += len(records)
        for record in records:
            if record not in seen:
                seen.add(record)
                unique_tasks.append(record)

    print(f"[INFO] B/D/H 三列合并记录原始条目数: {total_raw}，去重后剩余: {len(unique_tasks)}")

    # 注意：以下过程性元信息仅用于 Python 端控制台日志，不写入汇总文本
    # 以免 AI 在周报中引用"来源文件数/条目数/去重后条目数"等数据汇总过程信息
    lines: List[str] = []
    lines.append("以下为本周所有 Excel 中 B 列任务名称、D 列项目/需求、H 列工作描述的去重汇总列表：")
    lines.append("")
    for idx, task in enumerate(unique_tasks, start=1):
        lines.append(f"{idx}. {task}")

    full_text = "\n".join(lines)
    print(f"[INFO] Excel 汇总完成，接下来交由 AI 优化...")
    return full_text
