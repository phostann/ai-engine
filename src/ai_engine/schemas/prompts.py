from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SystemPromptTemplate(BaseModel):
    """工业级结构化 System Prompt 模板"""

    model_config = ConfigDict(frozen=True)

    role_identity: str = Field(..., description="角色身份与专业绑定")
    objectives: list[str] = Field(..., min_length=1, description="核心任务列表")
    constraints: list[str] = Field(default_factory=list, description="硬性禁令与约束")
    output_format: str = Field(..., description="输出格式规范")

    def render(self, context_vars: dict[str, Any] | None = None) -> str:
        """
        将结构化字段渲染为工业级标准 System Prompt 文本
        支持在指定区块通过安全占位符注入动态上下文
        """

        obj_text = "\n".join(f"- {obj}" for obj in self.objectives)
        con_text = "\n".join(f"- {con}" for con in self.constraints)

        prompt = f"""# 角色定义
{self.role_identity}

# 核心任务
{obj_text}

# 绝对约束
{con_text}

# 输出要求
{self.output_format}"""

        # TODO 4: 如果传入了 context_vars, 则使用安全的替换机制 (避免直接 eval)
        # 遍历 key, value 将 prompt 中的 {{key}} 替换为字符串格式的 value
        if context_vars:
            for k, v in context_vars.items():
                prompt = prompt.replace(f"{{{{{k}}}}}", str(v))

        return prompt.strip()
