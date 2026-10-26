from typing import Any

import tiktoken


class TokenBudgetGuard:
    """基于 tiktoken (Rust 内核) 的毫秒级本地 Token 计算与上下文预算守卫"""

    def __init__(
        self,
        encoding_name: str = "o200k_base",
        max_context_limit: int = 128000,
    ) -> None:
        # TODO 1: 使用 tiktoken.get_encoding 加载指定分词器
        self.encoding = tiktoken.get_encoding(encoding_name)
        self.max_context_limit = max_context_limit

    def count_text_tokens(self, text: str) -> int:
        """计算纯文本的精确 Token 数"""
        if not text:
            return 0
        # TODO 2: 使用 self.encoding.encode(text) 编码并返回长度
        return len(self.encoding.encode(text))

    def count_chat_tokens(
        self,
        messages: list[dict[str, Any]],
        model: str = "gpt-4o-mini",
    ) -> int:
        """
        精确计算符合 ChatML 规范的多轮消息 Token 总开销
        包含每条消息的控制头（<|im_start|>{role}\n）与结束标记（<|im_end|>）
        """
        # 兼容 gpt-4o / gpt-4o-mini 规范
        tokens_per_message = 3
        tokens_per_name = 1

        total_tokens = 0
        for message in messages:
            total_tokens += tokens_per_message
            for key, value in message.items():
                if isinstance(value, str):
                    total_tokens += self.count_text_tokens(value)
                if key == "name":
                    total_tokens += tokens_per_name

        # 模型生成前缀 <|im_start|>assistant 开销
        total_tokens += 3
        return total_tokens

    def validate_budget_or_raise(
        self,
        messages: list[dict[str, Any]],
        max_completion_tokens: int = 4096,
    ) -> None:
        """
        在发起网络请求前本地校验, 若上下文总和超出最大窗口，则提前报错拦截
        返回当前 Prompt 消耗的 Token 数
        """
        # prompt_tokens = self.count_chat_tokens(messages)

        # TODO 3: 校验 prompt_tokens + max_completion_tokens 是否超过 self.max_context_limit
        # 如果超出，抛出 ValueError 并打印当前 token 与限制值
        # if prompt_tokens + max_completion_tokens > self.max_context_limit:
        #     raise ValueError(
        #         f"上下文 Token 超限: 当前 Prompt ({prompt_tokens}) + "
        #         f"预期生成 ({max_completion_tokens}) > 最大限制 ({self.max_context_limit})"
        #     )
        pass
