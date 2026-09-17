"""Deterministic retrieval. Missing facts never satisfy a hard constraint."""
import asyncio
import copy
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.schemas.food import FoodFilters
from .amap_service import AmapService, safe_number, area_owner
from . import amap_service as area_settings

DATA_DIR = Path(__file__).parent.parent / "data"
FOODS_JSON = DATA_DIR / "foods.json"
AREAS = ("学校食堂", "南门", "西门龙湖时代天街")
UNKNOWN_LABELS = {
    "avg_price": "部分候选缺少人均参考价，预算是否满足待确认。",
    "distance": "部分候选缺少参考距离，距离条件是否满足待确认。",
    "rating": "部分候选缺少评分，评分条件是否满足待确认。",
    "taste": "部分候选缺少口味标签，口味条件是否满足待确认。",
    "cuisine": "部分候选缺少菜系信息，排除菜系条件是否满足待确认。",
    "meal_time": "部分候选缺少用餐时段信息，时段条件是否满足待确认。",
    "allergens": "过敏原信息未核实完整；待确认选项不代表过敏安全，请向商家核实食材及交叉接触风险。",
}


class FoodService:
    def __init__(self):
        self.amap_service = AmapService()
        self._local_foods = self._load_local_foods()

    def _load_local_foods(self) -> List[Dict]:
        try:
            with FOODS_JSON.open(encoding="utf-8") as source:
                return json.load(source)
        except (OSError, ValueError):
            return []

    def _local_for_area(self, area: str, fallback: bool = False) -> List[Dict]:
        fetched_at = datetime.now(timezone.utc).isoformat()
        foods = []
        for raw in self._local_foods:
            if raw.get("campus_area") != area:
                continue
            if fallback:
                location = f"{raw.get('longitude')},{raw.get('latitude')}"
                if area_owner({"location": location}, area_settings.CAMPUS_AREAS) != area:
                    continue
            food = copy.deepcopy(raw)
            record_id = str(food["id"])
            food.update({
                "id": f"local:{record_id}",
                "source_record_id": record_id,
                "source": "本地模拟数据",
                "is_mock": True,
                "fetched_at": fetched_at,
                "data_updated_at": raw.get("data_updated_at"),
                "avg_price": safe_number(raw.get("avg_price"), minimum=0),
                "rating": safe_number(raw.get("rating"), minimum=0, maximum=5),
                "distance": safe_number(raw.get("distance"), minimum=0, integer=True),
                "is_open": None,
                "opening_status": "unknown",
                "allergen_status": "partial" if raw.get("allergens") else "unknown",
                "distance_basis": "local_reference",
                "distance_note": "本地参考距离，原始数据未记录起点；不是当前位置路线距离。",
                "availability": "amap_fallback" if fallback else "local_only",
            })
            food["price_status"] = "reference" if food["avg_price"] is not None else "unknown"
            foods.append(food)
        return foods

    async def get_foods(self, campus_area: Optional[str] = None) -> List[Dict]:
        areas = [campus_area] if campus_area else list(AREAS)
        if self.amap_service.api_key:
            areas = [area for area in areas if area in area_settings.CAMPUS_AREAS]
        if not self.amap_service.api_key:
            return [food for area in areas for food in self._local_for_area(area)]

        # Region failures are independent, so one timeout cannot hide other live POIs.
        async def fetch_area(area):
            try:
                pois = await self.amap_service.search_nearby_pois(area)
                if pois:
                    return pois
            except Exception:
                pass
            return self._local_for_area(area, fallback=True)

        groups = await asyncio.gather(*(fetch_area(area) for area in areas))
        # Overlapping radii can return the same POI. Keep stable identities unique.
        foods_by_id = {}
        for group in groups:
            for food in group:
                foods_by_id.setdefault(food["id"], food)
        return list(foods_by_id.values())

    @staticmethod
    def _taste_matches(wanted: str, tags: List[str]) -> bool:
        if wanted in ("辣", "辛辣", "辣味"):
            return any("辣" in tag and tag not in ("不辣", "无辣") for tag in tags)
        return wanted in tags

    @classmethod
    def _assess(cls, food: Dict, filters: FoodFilters):
        rejected, unknown = set(), set()
        if filters.campus_area and food.get("campus_area") != filters.campus_area:
            rejected.add("campus_area")
        if food.get("id") in filters.exclude_ids:
            rejected.add("exclude_ids")
        if filters.keywords:
            text = f"{food.get('name') or ''} {food.get('cuisine') or ''}".lower()
            if filters.keywords.lower() not in text:
                rejected.add("keywords")

        tags = food.get("taste") or []
        if filters.taste or filters.exclude_taste:
            if not tags:
                unknown.add("taste")
            else:
                if not all(cls._taste_matches(tag, tags) for tag in filters.taste):
                    rejected.add("taste")
                if any(cls._taste_matches(tag, tags) for tag in filters.exclude_taste):
                    rejected.add("exclude_taste")
        if filters.exclude_cuisines:
            cuisine = food.get("cuisine") or ""
            if not cuisine:
                unknown.add("cuisine")
            elif any(tag in cuisine for tag in filters.exclude_cuisines):
                rejected.add("exclude_cuisines")

        for filter_name, field, lower_bound in (
            ("max_price", "avg_price", False),
            ("max_distance", "distance", False),
            ("min_rating", "rating", True),
        ):
            threshold = getattr(filters, filter_name)
            if threshold is None:
                continue
            value = safe_number(food.get(field), minimum=0, maximum=5 if field == "rating" else None)
            if value is None:
                unknown.add(field)
            elif (value < threshold if lower_bound else value > threshold):
                rejected.add(filter_name)

        if filters.meal_time:
            meal_times = food.get("meal_time") or []
            if not meal_times:
                unknown.add("meal_time")
            elif filters.meal_time not in meal_times:
                rejected.add("meal_time")
        if filters.exclude_allergens:
            recorded = food.get("allergens") or []
            if any(allergen in recorded for allergen in filters.exclude_allergens):
                rejected.add("exclude_allergens")
            elif food.get("allergen_status") != "verified_complete":
                unknown.add("allergens")
        return rejected, unknown

    @staticmethod
    def _sort_key(food: Dict, sort_by: str):
        rating = safe_number(food.get("rating"), minimum=0, maximum=5)
        distance = safe_number(food.get("distance"), minimum=0)
        price = safe_number(food.get("avg_price"), minimum=0)
        rating_key = -(rating if rating is not None else -1)
        distance_key = distance if distance is not None else float("inf")
        price_key = price if price is not None else float("inf")
        tail = str(food.get("id", ""))
        if sort_by == "price":
            return price_key, rating_key, distance_key, tail
        if sort_by == "reference_distance":
            return distance_key, rating_key, price_key, tail
        return rating_key, distance_key, price_key, tail

    def _search_candidates(self, filters: FoodFilters, candidates: List[Dict]) -> Dict:
        matched, pending = [], []
        rejected_by, unknown_by = Counter(), Counter()
        excluded = 0
        for food in candidates:
            rejected, unknown = self._assess(food, filters)
            if rejected:
                excluded += 1
                rejected_by.update(rejected)
                continue
            if unknown:
                candidate = copy.deepcopy(food)
                candidate["unknown_constraints"] = sorted(unknown)
                pending.append(candidate)
                unknown_by.update(unknown)
            else:
                matched.append(copy.deepcopy(food))
        matched.sort(key=lambda food: self._sort_key(food, filters.sort_by))
        pending.sort(key=lambda food: self._sort_key(food, filters.sort_by))
        results = matched[:filters.limit]
        unknowns = [UNKNOWN_LABELS[key] for key in sorted(unknown_by)]
        if any(food.get("is_mock") for food in candidates):
            unknowns.append("包含本地模拟数据，价格、评分及营业时段仅供参考。")
        if any(food.get("availability") == "amap_fallback" for food in candidates):
            unknowns.append("部分区域高德查询不可用或无结果，已使用该区域本地模拟数据。")
        if any(food.get("is_open") is None for food in results + pending[:filters.limit]):
            unknowns.append("未取得实时营业状态，不能确认餐厅现在营业。")
        if filters.max_distance is not None or filters.sort_by == "reference_distance":
            unknowns.append("距离筛选和排序仅使用各来源参考距离，不代表从你的位置出发的路线距离。")
        return {
            "results": results,
            "total_candidates": len(candidates),
            "filtered_count": len(matched),
            "returned_count": len(results),
            "using_realtime": any(food.get("source") == "高德实时POI" for food in candidates),
            "unknowns": unknowns,
            "pending_results": pending[:filters.limit],
            "filter_counts": {
                "matched": len(matched), "pending": len(pending), "excluded": excluded,
                "rejected_by": dict(sorted(rejected_by.items())),
                "unknown_by": dict(sorted(unknown_by.items())),
            },
        }

    async def search(self, filters: FoodFilters) -> Dict:
        if not isinstance(filters, FoodFilters):
            filters = FoodFilters.model_validate(filters)
        candidates = await self.get_foods(filters.campus_area)
        return self._search_candidates(filters, candidates)

    async def recommend_foods(
        self, campus_area=None, keywords=None, taste=None, max_price=None,
        max_distance=None, min_rating=None, meal_time=None, exclude_allergens=None,
        limit=10, exclude_taste=None, exclude_cuisines=None, exclude_ids=None, sort_by="rating",
    ) -> Dict:
        """Compatibility entry point; form and agent use exactly the same rules."""
        return await self.search(FoodFilters(
            campus_area=campus_area, keywords=keywords, taste=taste or [],
            max_price=max_price, max_distance=max_distance, min_rating=min_rating,
            meal_time=meal_time, exclude_allergens=exclude_allergens or [], limit=limit,
            exclude_taste=exclude_taste or [], exclude_cuisines=exclude_cuisines or [],
            exclude_ids=exclude_ids or [], sort_by=sort_by,
        ))

    async def suggest_changes(self, filters: FoodFilters, foods: Optional[List[Dict]] = None) -> List[Dict]:
        """Evaluate bounded counterfactuals on one snapshot; never mutate current filters."""
        if not isinstance(filters, FoodFilters):
            filters = FoodFilters.model_validate(filters)
        candidates = foods if foods is not None else await self.get_foods()
        baseline = self._search_candidates(filters, candidates)["filtered_count"]
        alternatives = []
        if filters.max_price is not None and filters.max_price < 10000:
            budget = min(filters.max_price + 5, 10000)
            alternatives.append(("raise_budget", f"人均预算改为 {budget:g} 元", {"max_price": budget}))
        if filters.min_rating is not None and filters.min_rating > 0:
            rating = max(filters.min_rating - 0.5, 0)
            alternatives.append(("lower_rating", f"最低评分改为 {rating:g}", {"min_rating": rating}))
        if filters.campus_area:
            alternatives.append(("all_areas", "查看所有区域", {"campus_area": None}))
        suggestions = []
        for identifier, label, changes in alternatives:
            proposed = FoodFilters.model_validate({**filters.model_dump(), **changes})
            count = self._search_candidates(proposed, candidates)["filtered_count"]
            if count > baseline:
                suggestions.append({"id": identifier, "label": label, "changes": changes, "count": count})
        return suggestions
