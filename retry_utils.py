# -*- coding: utf-8 -*-
"""重试工具模块（指数退避重试）。

提供通用的 HTTP 请求重试机制，适用于网络抖动、服务端临时故障等场景。
"""
import random
import time
from typing import Callable, Any, Tuple, Optional

import requests

from logger import get_logger

logger = get_logger(__name__)


def retry_request(
    func: Callable[..., requests.Response],
    *args,
    max_retries: int = 2,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    retryable_statuses: Tuple[int, ...] = (429, 500, 502, 503, 504),
    func_name: str = "API 请求",
    **kwargs,
) -> requests.Response:
    """带指数退避的 HTTP 请求重试。

    对网络异常（超时/连接错误）和可重试状态码（429/5xx）进行自动重试。

    Args:
        func: 发起 HTTP 请求的函数（如 requests.post, requests.get）
        max_retries: 最大重试次数（不含首次）
        base_delay: 首次重试等待秒数
        backoff: 退避因子（每次重试 delay *= backoff）
        retryable_statuses: 可重试的 HTTP 状态码
        func_name: 函数描述（用于日志输出）
    """
    last_exc: Optional[Exception] = None
    last_resp: Optional[requests.Response] = None

    for attempt in range(max_retries + 1):
        try:
            resp = func(*args, **kwargs)
            # 检查是否可重试的状态码
            if resp.status_code in retryable_statuses:
                if attempt == max_retries:
                    return resp
                delay = base_delay * (backoff ** attempt) + random.uniform(0, 0.5)
                logger.warning("%s HTTP %s，%.1f秒后重试 (第%d次/%d)...",
                               func_name, resp.status_code, delay, attempt + 1, max_retries)
                time.sleep(delay)
                continue
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt == max_retries:
                raise
            delay = base_delay * (backoff ** attempt) + random.uniform(0, 0.5)
            logger.warning("%s 网络异常: %s，%.1f秒后重试 (第%d次/%d)...",
                           func_name, e, delay, attempt + 1, max_retries)
            time.sleep(delay)
            continue
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt == max_retries:
                raise
            delay = base_delay * (backoff ** attempt) + random.uniform(0, 0.5)
            logger.warning("%s 请求异常: %s，%.1f秒后重试 (第%d次/%d)...",
                           func_name, e, delay, attempt + 1, max_retries)
            time.sleep(delay)
            continue

    # 所有重试耗尽
    if last_exc:
        raise last_exc  # type: ignore[misc]
    if last_resp is not None:
        return last_resp
    raise RuntimeError(f"{func_name} 重试耗尽，请求失败")