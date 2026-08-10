# -*- coding: utf-8 -*-
"""pytest 公共配置。

项目模块（output_resolver / text_utils / excel_aggregator 等）都以顶层模块方式互相
导入（如 `from output_resolver import ...`），运行时依赖脚本所在目录在 sys.path 中。
此处将项目根目录加入 sys.path，使 tests/ 下的用例可以直接 import 被测模块。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
