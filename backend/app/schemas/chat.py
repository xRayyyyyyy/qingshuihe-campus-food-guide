"""Validated wire contracts for conversation and model-produced decisions."""

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


ConstraintField = Literal[
    "campus_area", "keywords", "taste", "exclude_taste", "exclude_cuisines",
    "max_price", "max_distance", "min_rating", "meal_time", "exclude_allergens",
    "exclude_ids", "sort_by", "limit",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ChatRequest(StrictModel):
    message: str = Field(default="", max_length=2000, strict=True)
    session_id: str | None = Field(default=None, max_length=36)
    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)
    expected_state_version: int | None = Field(default=None, ge=0, strict=True)
    ui_changes: dict[str, Any] | None = None

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("session_id must be a UUID") from None

    @field_validator("ui_changes")
    @classmethod
    def validate_ui_changes(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(value) > 20:
            raise ValueError("Too many UI changes")
        return value


class ConstraintUpdate(StrictModel):
    field: ConstraintField
    value: Any
    evidence: str = Field(min_length=1, max_length=2000, strict=True)


class ConstraintClear(StrictModel):
    field: ConstraintField
    evidence: str = Field(min_length=1, max_length=2000, strict=True)


class InterpretedRequest(StrictModel):
    action: Literal["search", "details", "compare", "explain", "suggest"] = "search"
    updates: list[ConstraintUpdate] = Field(default_factory=list, max_length=14)
    clear: list[ConstraintClear] = Field(default_factory=list, max_length=14)
    reference_indices: list[int] = Field(default_factory=list, max_length=3)
    clarification: str | None = Field(default=None, max_length=300)
    replace_previous: bool = Field(default=False, strict=True)
    unsupported: Literal["none", "walking_route", "live_opening", "dietary_claim"] = "none"

    @field_validator("reference_indices")
    @classmethod
    def validate_indices(cls, value: list[int]) -> list[int]:
        if any(index < 1 or index > 20 for index in value) or len(set(value)) != len(value):
            raise ValueError("References must be unique one-based indices between 1 and 20")
        return value


EvidenceField = Literal[
    "campus_area", "cuisine", "taste", "avg_price", "rating", "distance",
    "meal_time", "allergens", "opening_hours", "source",
]


class RecommendationEvidence(StrictModel):
    food_id: str = Field(min_length=1, max_length=128, strict=True)
    evidence_fields: list[EvidenceField] = Field(default_factory=list, max_length=10)


class FinalAnswer(StrictModel):
    recommendations: list[RecommendationEvidence] = Field(default_factory=list, max_length=3)
    next_action: Literal["completed", "suggest", "clarify"] = "completed"


def function_schema(name: str, description: str, model: type[BaseModel]) -> dict:
    """Inline Pydantic references for compatible function-calling providers."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(item: Any) -> Any:
        if isinstance(item, list):
            return [inline(child) for child in item]
        if isinstance(item, dict):
            if "$ref" in item:
                return inline(definitions[item["$ref"].rsplit("/", 1)[-1]])
            return {key: inline(child) for key, child in item.items() if key != "title"}
        return item

    return {"type": "function", "function": {
        "name": name, "description": description, "parameters": inline(schema),
    }}
