# -*- coding: utf-8 -*-
"""日志模块。

负责：
- 初始化周报运行日志：同时输出到控制台与 logs/ 目录下的 txt 文件
- 日志文件按「周报名称」命名，如 logs/Vue2026.7.13-7.19周报.txt
- 通过 stdout/stderr tee 重定向，将全流程所有 print 输出同步写入日志文件，
  保证每一步骤（节假日检查 / CRM 下载 / Excel 汇总 / AI 生成 / 钉钉审核 / 发送）均有留存
"""
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# 日志目录（相对脚本所在目录）
LOG_DIR = Path(__file__).parent / "logs"

# 首次包装前的原始流（tee 始终以原始流为基准，避免重复包装）
_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr

# 当前 tee 打开的日志文件句柄
_TEE_FILE_HANDLES: List = []

# 当前日志文件路径（供外部查询）
CURRENT_LOG_PATH: Optional[Path] = None


class _TeeStream:
    """将写入的内容同时转发到多个流（原始流 + 日志文件）。"""

    def __init__(self, *streams) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for s in self._streams:
            try:
                s.write(data)
            except Exception:
                pass
        return len(data)

    def flush(self) -> None:
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False

    def fileno(self):
        # 返回第一个原始流（stdout/stderr）的文件描述符，避免依赖该属性的库报错
        return self._streams[0].fileno()


def _redirect_stdout_stderr(log_path: Path) -> None:
    """将 sys.stdout / sys.stderr 包装为 tee，同时写入原流与日志文件。"""
    global _TEE_FILE_HANDLES
    # 关闭上一次打开的日志文件句柄（重复初始化时）
    for fh in _TEE_FILE_HANDLES:
        try:
            fh.close()
        except Exception:
            pass
    _TEE_FILE_HANDLES = []

    try:
        log_fh = open(log_path, "a", encoding="utf-8")
    except OSError:
        return
    _TEE_FILE_HANDLES.append(log_fh)

    sys.stdout = _TeeStream(_ORIGINAL_STDOUT, log_fh)
    sys.stderr = _TeeStream(_ORIGINAL_STDERR, log_fh)


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

    # 清理 root logger 已有 handlers，避免重复
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    level = logging.DEBUG if debug else logging.INFO
    root.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 handler（UTF-8 编码，保证中文可读）
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # 控制台 handler
    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    # 第三方库日志降噪
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("dingtalk_stream").setLevel(logging.WARNING)

    # print 输出（tee）同步写入日志文件
    _redirect_stdout_stderr(log_path)

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
