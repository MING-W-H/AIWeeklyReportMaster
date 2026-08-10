# -*- coding: utf-8 -*-
"""日志模块。

负责：
- 初始化周报运行日志：同时输出到控制台与 logs/ 目录下的 txt 文件
- 日志文件按「周报名称」命名，如 logs/Vue2026.7.13-7.19周报.txt
- 全流程统一使用标准 logging 输出（时间戳 + 级别），不再依赖 print / stdout tee 重定向
- get_logger 保证未调用 init_logging 的独立脚本也能获得带时间戳的控制台输出
- 启动时自动清理 90 天前的旧日志文件
"""
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# 日志目录（相对脚本所在目录）
LOG_DIR = Path(__file__).parent / "logs"

# 统一日志格式（时间戳 + 级别）
_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_FORMATTER = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

# 当前日志文件路径（供外部查询）
CURRENT_LOG_PATH: Optional[Path] = None


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """返回模块级 logger，并在 root 尚无 handler 时补一个控制台 handler。

    独立脚本（不调用 init_logging）通过它也能获得带时间戳/级别的控制台输出；
    主流程调用 init_logging 后，模块 logger 会向上传播到 root 的文件 + 控制台 handler。
    """
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_FORMATTER)
        handler.setLevel(logging.INFO)
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    return logging.getLogger(name)


def cleanup_old_logs(days: int = 90) -> int:
    """删除 logs/ 目录中修改时间超过指定天数的旧日志文件。

    Returns:
        删除的文件数
    """
    if not LOG_DIR.exists():
        return 0
    now = time.time()
    cutoff = now - days * 86400
    removed = 0
    for f in LOG_DIR.iterdir():
        if not f.is_file():
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    if removed:
        logging.info("已清理 %d 个 %d 天前的旧日志文件", removed, days)
    return removed


def init_logging(run_label: str, debug: bool = False) -> Path:
    """初始化周报运行日志。

    Args:
        run_label: 周报名称（如 Vue2026.7.13-7.19周报），用作日志文件的基础名
        debug: 为 True 时记录 DEBUG 级别日志（对应 --debug 参数）

    Returns:
        日志文件绝对路径
    """
    global CURRENT_LOG_PATH
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{run_label}.txt"

    # 清理 root logger 已有 handlers，避免重复（含 get_logger 补的默认控制台 handler）
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    level = logging.DEBUG if debug else logging.INFO
    root.setLevel(level)

    # 文件 handler（UTF-8 编码，保证中文可读）
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(_FORMATTER)
    root.addHandler(fh)

    # 控制台 handler
    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(_FORMATTER)
    root.addHandler(sh)

    # 第三方库日志降噪
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("dingtalk_stream").setLevel(logging.WARNING)

    # 启动时自动清理 90 天前的旧日志（handler 已就绪，清理信息可正常输出）
    cleanup_old_logs(days=90)

    CURRENT_LOG_PATH = log_path

    # 记录运行环境信息
    logging.info("=" * 60)
    logging.info("AI 周报生成器 - 运行日志")
    logging.info(f"日志文件: {log_path}")
    logging.info(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"工作目录: {Path.cwd()}")
    logging.info(f"Python 版本: {sys.version.split()[0]}")
    logging.info("=" * 60)
    return log_path
