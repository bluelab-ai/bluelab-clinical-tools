#!/usr/bin/env python3
"""
AI 调用重试工具
==============
为所有 AI 调用添加重试机制，处理临时 API 错误
"""

import time
from typing import Any, Callable


def call_ai_with_retry(
    call_func: Callable,
    validate_func: Callable[[Any], bool],
    max_retries: int = 3,
    retry_delay: float = 2.0,
    log_func: Callable[[str], None] = None
) -> Any:
    """
    调用 AI 并在失败时重试

    参数:
        call_func: 调用 AI 的函数，返回响应对象
        validate_func: 验证响应是否有效的函数，返回 True/False
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）
        log_func: 日志函数

    返回:
        验证通过的响应对象

    异常:
        所有重试都失败后抛出最后一个异常
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            response = call_func()

            if validate_func(response):
                return response

            # 验证失败，准备重试
            if attempt < max_retries - 1:
                if log_func:
                    log_func(f"响应验证失败，{retry_delay}秒后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(retry_delay)

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                if log_func:
                    log_func(f"调用出错: {e}，{retry_delay}秒后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(retry_delay)

    # 所有重试都失败
    if last_error:
        raise last_error
    raise ValueError("AI 调用失败，未获取到有效响应")


def has_tool_use(response, tool_name: str = None) -> bool:
    """
    检查响应是否包含 tool_use

    参数:
        response: AI 响应对象
        tool_name: 工具名称（可选，如果指定则检查特定工具）

    返回:
        是否包含 tool_use
    """
    for block in response.content:
        if block.type == "tool_use":
            if tool_name is None or block.name == tool_name:
                return True
    return False


def extract_tool_use(response, tool_name: str) -> dict:
    """
    从响应中提取 tool_use 结果

    参数:
        response: AI 响应对象
        tool_name: 工具名称

    返回:
        tool_use 的 input 字典

    异常:
        未找到 tool_use 时抛出 ValueError
    """
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input
    raise ValueError(f"未找到 tool_use 响应: {tool_name}")
