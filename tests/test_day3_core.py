import pytest
from pydantic import ValidationError

from ai_engine.schemas.agent_protocol import (
    AGENT_DECISION_ADAPTER,
    VectorSearchAction,
)
from ai_engine.schemas.extraction import ChapterExtractionResult


def test_chapter_extraction_and_camel_case_serialization() -> None:
    """测试 JSON 零拷贝解析、前置空格清洗、跨字段校验与前端驼峰导出"""
    raw_llm_output = """
    {
        "chapter_index": 1,
        "chapter_title": "马赛港的归航",
        "summary": "唐泰斯带着法老号归来，却遭唐格拉尔与费尔南联手诬陷。",
        "relations": [
            {
                "source_character": " “唐格拉尔” ",
                "target_character": "唐泰斯",
                "relation_type": "enemy",
                "evidence_quote": "唐格拉尔用左手写下了那封致命的匿名检举信。"
            }
        ]
    }
    """
    # 1. 使用 Rust 内核直接校验原始 JSON 字符串
    result = ChapterExtractionResult.model_validate_json(raw_llm_output)
    assert result.chapter_index == 1
    # 验证 @field_validator 自动洗掉了前后的空格与中文引号
    assert result.relations[0].source_character == "唐格拉尔"

    # 2. 导出给前端时，使用 by_alias=True 自动将下划线转为驼峰 (chapterIndex / chapterTitle)
    frontend_dict = result.model_dump(by_alias=True)
    assert frontend_dict["chapterIndex"] == 1
    assert frontend_dict["chapterTitle"] == "马赛港的归航"

    # 3. 导出给大模型的 JSON Schema
    schema = ChapterExtractionResult.model_json_schema()
    assert "properties" in schema
    assert "$defs" in schema  # 包含子模型 CharacterRelation 的定义


def test_self_relation_validation_error() -> None:
    """测试跨字段校验器拦截自己指向自己的人物关系"""
    invalid_json = """
    {
        "chapter_index": 1,
        "chapter_title": "测试章节",
        "summary": "这是一段超过十个字的正常章节梗概内容。",
        "relations": [
            {
                "source_character": "唐泰斯",
                "target_character": "唐泰斯",
                "relation_type": "ally",
                "evidence_quote": "自言自语"
            }
        ]
    }
    """
    with pytest.raises(ValidationError) as exc_info:
        ChapterExtractionResult.model_validate_json(invalid_json)
    # Pydantic v2 可以输出极其清晰的错误定位信息（可直接喂回给大模型重试）
    assert "人物关系不能指向自身" in str(exc_info.value)


def test_discriminated_union_routing() -> None:
    """测试 O(1) 多态路由与不可变对象约束"""
    raw_search = '{"action_type": "vector_search", "query": "伊夫堡监狱", "top_k": 3}'
    decision = AGENT_DECISION_ADAPTER.validate_json(raw_search)
    assert isinstance(decision, VectorSearchAction)
    assert decision.top_k == 3

    with pytest.raises(ValidationError, match="frozen"):
        decision.top_k = 99

    # 测试高风险操作原因过短时触发拦截
    invalid_approval = (
        '{"action_type": "human_approval", "risk_level": "high", '
        '"reason": "太短", "payload_summary": "drop table"}'
    )
    with pytest.raises(ValidationError, match="至少 10 个字符"):
        AGENT_DECISION_ADAPTER.validate_json(invalid_approval)
