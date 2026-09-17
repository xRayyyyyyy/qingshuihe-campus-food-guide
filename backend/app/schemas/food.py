"""Validated filters shared by form requests and agent tools."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


CampusArea = Literal["学校食堂", "南门", "西门龙湖时代天街"]
MealTime = Literal["早餐", "午餐", "晚餐", "夜宵"]


class FoodFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    campus_area: CampusArea | None = None
    keywords: str | None = Field(default=None, max_length=100)
    taste: list[str] = Field(default_factory=list, max_length=30)
    exclude_taste: list[str] = Field(default_factory=list, max_length=30)
    exclude_cuisines: list[str] = Field(default_factory=list, max_length=30)
    max_price: float | None = Field(default=None, ge=0, le=10000)
    max_distance: int | None = Field(default=None, ge=0, le=100000)
    min_rating: float | None = Field(default=None, ge=0, le=5)
    meal_time: MealTime | None = None
    exclude_allergens: list[str] = Field(default_factory=list, max_length=30)
    exclude_ids: list[str] = Field(default_factory=list, max_length=200)
    sort_by: Literal["rating", "price", "reference_distance"] = "rating"
    limit: int = Field(default=10, ge=1, le=20)

    @field_validator("*", mode="before")
    @classmethod
    def trim_strings(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator(
        "taste", "exclude_taste", "exclude_cuisines", "exclude_allergens", "exclude_ids",
        mode="before",
    )
    @classmethod
    def clean_lists(cls, value):
        if value is None or value == "":
            return []
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("筛选标签必须是字符串列表")
        cleaned = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if any(len(item) > 100 for item in cleaned):
            raise ValueError("单个筛选标签不能超过 100 个字符")
        return cleaned

    @field_validator("max_price", "max_distance", "min_rating", "limit", mode="before")
    @classmethod
    def disallow_boolean_numbers(cls, value):
        if isinstance(value, bool):
            raise ValueError("数值条件不能使用布尔值")
        return value
