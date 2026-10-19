from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class BaseAgentAction(BaseModel):
    """所有 Agent 动作的不可变基类"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class VectorSearchAction(BaseAgentAction):
    action_type: Literal["vector_search"] = "vector_search"
    query: str = Field(..., min_length=2, description="语义检索关键词")
    top_k: int = Field(default=5, ge=1, le=20, description="召回文档块数量")
    filters: dict[str, str | int] = Field(default_factory=dict, description="元数据过滤条件")


class HumanApprovalAction(BaseAgentAction):
    action_type: Literal["human_approval"] = "human_approval"
    risk_level: Literal["low", "medium", "high"]
    reason: str = Field(..., description="请求人工介入的原因")
    payload_summary: str

    @model_validator(mode="after")
    def check_high_risk_reason(self) -> "HumanApprovalAction":
        if self.risk_level == "high" and len(self.reason) < 10:
            raise ValueError("高风险(high)操作必须提供至少 10 个字符的详细审批原因！")

        return self


class FinalReplyAction(BaseAgentAction):
    action_type: Literal["final_reply"] = "final_reply"
    answer: str = Field(..., description="最终展示给用户的 Markdown 回复")
    citations: list[int] = Field(default_factory=list, description="引用的原文段落编号")


# 声明以 action_type 为路由键的多态联合类型
type AgentStepDecision = Annotated[
    VectorSearchAction | HumanApprovalAction | FinalReplyAction, Field(discriminator="action_type")
]

# 编译模块级单例 TypeAdapter（切勿在请求函数内部重复实例化 TypeAdapter）
AGENT_DECISION_ADAPTER: TypeAdapter[AgentStepDecision] = TypeAdapter(AgentStepDecision)
