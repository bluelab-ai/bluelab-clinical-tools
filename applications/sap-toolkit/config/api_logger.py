"""
API 调用日志记录器
==================
记录每次 API 调用的输入、输出和思考过程，保存为可读的文本格式。
"""

import json
import os
from datetime import datetime


class APILogger:
    """API 调用日志记录器"""

    def __init__(self, log_dir: str, task_name: str = ""):
        """
        初始化日志记录器

        Args:
            log_dir: 日志目录路径
            task_name: 任务名称，用于日志文件名（如 "主要终点"、"安全性评价"）
        """
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        # 生成带时间戳和任务名的日志文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if task_name:
            safe_name = task_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
            self.log_file = os.path.join(log_dir, f"{timestamp}_{safe_name}.md")
        else:
            import uuid
            short_id = uuid.uuid4().hex[:6]
            self.log_file = os.path.join(log_dir, f"{timestamp}_{short_id}.md")
        self.call_count = 0

        # 写入文件头
        with open(self.log_file, "w", encoding="utf-8") as f:
            f.write(f"# API 调用日志\n\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    def log_call(
        self,
        func_name: str,
        model: str,
        max_tokens: int,
        temperature: float = None,
        system: str = None,
        messages: list = None,
        tools: list = None,
        tool_choice: dict = None,
        extra_body: dict = None,
        response=None,
        thinking_text: str = None,
    ):
        """
        记录一次 API 调用

        Args:
            func_name: 调用的函数名
            model: 模型名称
            max_tokens: 最大 token 数
            temperature: 温度参数
            system: 系统提示
            messages: 消息列表
            tools: 工具定义列表
            tool_choice: 工具选择
            extra_body: 额外参数（含 thinking 配置）
            response: API 响应对象
            thinking_text: streaming 模式下收集的思考文本
        """
        self.call_count += 1
        timestamp = datetime.now().strftime("%H:%M:%S")

        # 解析 thinking 配置
        thinking_config = "未启用"
        if extra_body and "thinking" in extra_body:
            tc = extra_body["thinking"]
            if tc.get("type") == "enabled":
                thinking_config = f"enabled, budget_tokens={tc.get('budget_tokens', '?')}"
            else:
                thinking_config = "disabled"

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"---\n\n")
            f.write(f"## 调用 #{self.call_count} — {func_name}\n\n")
            f.write(f"- 时间: {timestamp}\n")
            f.write(f"- 模型: {model}\n")
            f.write(f"- max_tokens: {max_tokens}\n")
            if temperature is not None:
                f.write(f"- temperature: {temperature}\n")
            f.write(f"- thinking: {thinking_config}\n")
            f.write(f"\n")

            # === 输入 ===
            f.write(f"### 输入\n\n")

            # System prompt
            if system:
                # 截断过长的 system prompt
                if len(system) > 2000:
                    f.write(f"**System** ({len(system)} 字符，前 2000 字符):\n\n")
                    f.write(f"```\n{system[:2000]}\n...(已截断)\n```\n\n")
                else:
                    f.write(f"**System**:\n\n")
                    f.write(f"```\n{system}\n```\n\n")
            else:
                f.write(f"**System**: (无)\n\n")

            # Messages
            if messages:
                f.write(f"**Messages**:\n\n")
                sanitized = self._sanitize_messages(messages)
                messages_json = json.dumps(sanitized, ensure_ascii=False, indent=2)
                if len(messages_json) > 5000:
                    f.write(f"```json\n{messages_json[:5000]}\n...(已截断)\n```\n\n")
                else:
                    f.write(f"```json\n{messages_json}\n```\n\n")

            # Tools
            if tools:
                f.write(f"**Tools** ({len(tools)} 个): ")
                tool_names = [t.get("name", "?") for t in tools]
                f.write(f"{', '.join(tool_names)}\n\n")

            # Tool choice
            if tool_choice:
                f.write(f"**Tool Choice**: `{json.dumps(tool_choice, ensure_ascii=False)}`\n\n")

            # === 输出 ===
            f.write(f"### 输出\n\n")

            if response:
                # 响应元数据
                if hasattr(response, "stop_reason"):
                    f.write(f"- stop_reason: {response.stop_reason}\n")
                if hasattr(response, "usage") and response.usage:
                    usage = response.usage
                    f.write(f"- input_tokens: {getattr(usage, 'input_tokens', '?')}\n")
                    f.write(f"- output_tokens: {getattr(usage, 'output_tokens', '?')}\n")
                    cache_read = getattr(usage, 'cache_read_input_tokens', None)
                    if cache_read:
                        f.write(f"- cache_read_tokens: {cache_read}\n")
                    cache_create = getattr(usage, 'cache_creation_input_tokens', None)
                    if cache_create:
                        f.write(f"- cache_creation_tokens: {cache_create}\n")
                f.write(f"\n")

                # 遍历 content blocks
                for block in response.content:
                    if block.type == "text":
                        text = block.text
                        f.write(f"**Text** ({len(text)} 字符):\n\n")
                        if len(text) > 5000:
                            f.write(f"```\n{text[:5000]}\n...(已截断)\n```\n\n")
                        else:
                            f.write(f"```\n{text}\n```\n\n")

                    elif block.type == "thinking":
                        thinking = block.thinking
                        f.write(f"**Thinking** ({len(thinking)} 字符):\n\n")
                        f.write(f"```\n{thinking}\n```\n\n")

                    elif block.type == "tool_use":
                        f.write(f"**Tool Use**: {block.name}\n\n")
                        input_json = json.dumps(block.input, ensure_ascii=False, indent=2)
                        if len(input_json) > 3000:
                            f.write(f"```json\n{input_json[:3000]}\n...(已截断)\n```\n\n")
                        else:
                            f.write(f"```json\n{input_json}\n```\n\n")

            # streaming 模式的 thinking
            elif thinking_text:
                f.write(f"**Thinking** ({len(thinking_text)} 字符, streaming):\n\n")
                f.write(f"```\n{thinking_text}\n```\n\n")

            f.write(f"\n")

    def _sanitize_messages(self, messages: list) -> list:
        """
        清理消息中的图片数据，替换为占位符
        将 Anthropic SDK 对象转为可序列化的 dict
        """
        sanitized = []
        for msg in messages:
            if isinstance(msg, dict):
                sanitized_msg = dict(msg)
                content = msg.get("content")
                if isinstance(content, list):
                    sanitized_content = []
                    for item in content:
                        sanitized_content.append(self._sanitize_block(item))
                    sanitized_msg["content"] = sanitized_content
                sanitized.append(sanitized_msg)
            else:
                # 非 dict 消息，尝试转为 dict
                sanitized.append(self._sanitize_block(msg))
        return sanitized

    def _sanitize_block(self, item):
        """将单个 content block 转为可序列化的 dict"""
        # Anthropic SDK 对象（ThinkingBlock, TextBlock, ToolUseBlock 等）
        if hasattr(item, "type"):
            block_type = item.type
            if block_type == "thinking":
                thinking = getattr(item, "thinking", "")
                return {"type": "thinking", "thinking": thinking[:500] + "..." if len(thinking) > 500 else thinking}
            elif block_type == "text":
                text = getattr(item, "text", "")
                return {"type": "text", "text": text[:2000] + "..." if len(text) > 2000 else text}
            elif block_type == "tool_use":
                return {
                    "type": "tool_use",
                    "name": getattr(item, "name", "?"),
                    "input": getattr(item, "input", {}),
                }
            elif block_type == "tool_result":
                content = getattr(item, "content", "")
                if isinstance(content, str) and len(content) > 1000:
                    content = content[:1000] + "...(已截断)"
                return {
                    "type": "tool_result",
                    "tool_use_id": getattr(item, "tool_use_id", "?"),
                    "content": content,
                }
            else:
                return {"type": block_type, "data": str(item)[:500]}

        # 已经是 dict
        if isinstance(item, dict):
            if item.get("type") == "image":
                source = item.get("source", {})
                data = source.get("data", "")
                size = len(data) if data else 0
                return {
                    "type": "image",
                    "source": {
                        "type": source.get("type", "base64"),
                        "media_type": source.get("media_type", "image/png"),
                        "data": f"[图片: {size} 字节]"
                    }
                }
            elif item.get("type") == "tool_result":
                result_content = item.get("content", "")
                if isinstance(result_content, str) and len(result_content) > 1000:
                    item = dict(item)
                    item["content"] = result_content[:1000] + "...(已截断)"
            return item

        # 其他类型，转为字符串
        return str(item)[:500]
