from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 定义可复用的约束类型
type NonEmptyStr = Annotated[str, Field(min_length=1, description="非空字符串")]
type ConfidenceScore = Annotated[float, Field(ge=0.0, le=1.0, description="0到1之间的置信度得分")]


class CharacterRelation(BaseModel):
    """任务关系子模型"""

    model_config = ConfigDict(extra="forbid")

    source_character: NonEmptyStr = Field(description="主动方人物姓名")
    target_character: NonEmptyStr = Field(description="被动方人物姓名")
    relation_type: Literal["ally", "enemy", "mentor", "family", "unknown"]
    evidence_quote: NonEmptyStr = Field(description="原文中的证据原句摘录")

    @field_validator("source_character", "target_character", mode="before")
    @classmethod
    def strip_whitespace(cls, v: object) -> object:
        """单字段前置清洗器（mode='before'）: 在进入 Rust 类型校验前自动去除收尾空格和书名号"""
        if isinstance(v, str):
            return v.strip().strip("《》“”\"'")
        return v

    @model_validator(mode="after")
    def check_not_self_relation(self) -> "CharacterRelation":
        """跨字段后置校验器（mode='after'）: 所以单字段校验通过后，检查两个人物不能是同一个人"""
        if self.source_character == self.target_character:
            raise ValueError(f"人物关系不能指向自身：{self.source_character}")
        return self


class ChapterExtractionResult(BaseModel):
    """章节深度拆解结构化提取结果（同时支持大模型输出解析与前端驼峰序列化）"""

    model_config = ConfigDict(
        extra="forbid",  # 严禁大模型瞎编未定义的字段
        populate_by_name=True,  # 允许同时通过 Python 属性名或 alias 别名赋值
    )

    chapter_index: Annotated[int, Field(ge=1, alias="chapterIndex")]
    chapter_title: NonEmptyStr = Field(alias="chapterTitle")
    summary: Annotated[str, Field(min_length=10, max_length=500, description="章节核心梗概")]
    relations: list[CharacterRelation] = Field(
        default_factory=list, description="提取出的人物关系表"
    )
    confidence: ConfidenceScore = 0.9
