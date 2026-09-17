"""Schemas and argument validation for the deliberately small food tool registry."""

import json
from typing import Annotated

from pydantic import Field, ValidationError, field_validator

from app.schemas.chat import StrictModel, function_schema


FoodId = Annotated[str, Field(min_length=1, max_length=128, strict=True)]


class NoArguments(StrictModel):
    pass


class FoodDetailsArguments(StrictModel):
    food_ids: list[FoodId] = Field(min_length=1, max_length=3)

    @field_validator("food_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Food IDs must be unique")
        return value


class CompareFoodArguments(FoodDetailsArguments):
    food_ids: list[FoodId] = Field(min_length=2, max_length=3)


TOOL_MODELS = {
    "search_foods": NoArguments,
    "get_food_details": FoodDetailsArguments,
    "compare_foods": CompareFoodArguments,
    "suggest_constraint_changes": NoArguments,
}

TOOLS = [
    function_schema("search_foods", "按服务器已验证的当前会话条件检索餐厅，不接受条件覆盖。", NoArguments),
    function_schema("get_food_details", "查看已提供候选中 1 至 3 家餐厅的来源与详情。", FoodDetailsArguments),
    function_schema("compare_foods", "基于数据比较已提供候选中 2 至 3 家餐厅。", CompareFoodArguments),
    function_schema("suggest_constraint_changes", "基于当前条件给出可选择的调整建议；不改变条件或放宽禁忌。", NoArguments),
]


class ToolValidationError(ValueError):
    """Safe validation failure: never include untrusted arguments in error output."""


def validate_tool_call(name: str, raw_args: str | dict) -> dict:
    model = TOOL_MODELS.get(name)
    if model is None:
        raise ToolValidationError("unknown_tool")
    try:
        if isinstance(raw_args, str):
            if len(raw_args) > 16000:
                raise ToolValidationError("invalid_arguments")
            arguments = json.loads(raw_args)
        elif isinstance(raw_args, dict):
            arguments = raw_args
        else:
            raise ToolValidationError("invalid_arguments")
        if not isinstance(arguments, dict):
            raise ToolValidationError("invalid_arguments")
        return model.model_validate(arguments, strict=True).model_dump()
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise ToolValidationError("invalid_arguments") from None
