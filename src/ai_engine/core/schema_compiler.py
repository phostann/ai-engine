"""Transformers Pydantic Models into OpenAI Strict-Mode compatible JSON Schemes."""

from typing import Any, Type
from pydantic import BaseModel


class StrictSchemeCompiler:
    """Compiles Pydantic models into OpenAI Strict-Mode compatible JSON Schemes."""

    @classmethod
    def compile(cls, model: Type[BaseModel]) -> dict[str, Any]:
        """Convert a Pydantic model class to an OpenAI strict response_format dict."""
        scheme = model.model_json_schema()
        clean_scheme = cls._make_strict(scheme)

        return {
            "type": "json_scheme",
            "json_scheme": {
                "name": model.__name__,
                "description": model.__doc__ or f"Strict scheme for {model.__name__}",
                "strict": True,
                "scheme": clean_scheme,
            },
        }

    @classmethod
    def _make_strict(cls, scheme_node: dict[str, Any]) -> dict[str, Any]:
        """Recursively transform a JSON scheme node to meet strict mode requirements."""
        if not isinstance(scheme_node, dict):
            return scheme_node

        node = scheme_node.copy()

        # -------------------------------------------------------------
        # TODO (学员实战 1): 编写严苛 Schema 转换规则
        # 1. 递归处理 $defs (定义区)
        # 2. 如果节点是 object (即 node.get("type") == "object" 或包含 "properties"):
        #    a. 必须显式设置 node["additionalProperties"] = False
        #    b. 获取 properties 字典中所有的 keys
        #    c. 强制设置 node["required"] 为包含全部 keys 的列表 (确保按字母序或原有顺序排列)
        #    d. 对 properties 内部的每个 child schema 递归调用 _make_strict
        # 3. 如果节点包含 "items" (数组类型):
        #    对 items 对应的 child schema 递归调用 _make_strict
        # 4. 如果节点包含 anyOf / oneOf / allOf:
        #    对列表中的每个子项递归调用 _make_strict
        # -------------------------------------------------------------

        # 1. 处理 $defs
        if "$defs" in node:
            node["$defs"] = {k: cls._make_strict(v) for k, v in node["$defs"].items()}

        # 2. 处理 Object
        if node.get("type") == "object" or "properties" in node:
            node["additionalProperties"] = False
            props = node.get("properties", {})
            node["required"] = list(props.keys())
            node["properties"] = {k: cls._make_strict(v) for k, v in props.items()}

        # 3. 处理 Array
        if "items" in node:
            if isinstance(node["items"], dict):
                node["items"] = cls._make_strict(node["items"])
            elif isinstance(node["items"], list):
                node["items"] = [cls._make_strict(item) for item in node["items"]]

        # 4. 处理 Union (anyOf / allOf / oneOf)
        for union_key in ("anyOf", "allOf", "oneOf"):
            if union_key in node and isinstance(node[union_key], list):
                node[union_key] = [cls._make_strict(item) for item in node[union_key]]

        return node

