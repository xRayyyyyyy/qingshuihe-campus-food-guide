"""餐饮推荐服务模块"""
import json
import os
from typing import List, Dict, Optional
from pathlib import Path
from .amap_service import AmapService

# 本地备用数据路径
DATA_DIR = Path(__file__).parent.parent / "data"
FOODS_JSON = DATA_DIR / "foods.json"


class FoodService:
    """餐饮推荐服务类"""

    def __init__(self):
        self.amap_service = AmapService()
        self._local_foods = self._load_local_foods()

    def _load_local_foods(self) -> List[Dict]:
        """加载本地备用餐饮数据"""
        try:
            with open(FOODS_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"加载本地数据失败: {e}")
            return []

    async def get_foods(self, campus_area: Optional[str] = None) -> List[Dict]:
        """
        获取餐饮列表，优先返回高德实时POI

        Args:
            campus_area: 校区区域筛选

        Returns:
            餐饮列表
        """
        # 尝试获取实时POI
        if self.amap_service.api_key:
            if campus_area:
                # 指定了区域，查询该区域的实时POI
                try:
                    real_pois = await self.amap_service.search_nearby_pois(campus_area)
                    if real_pois:
                        return real_pois
                except Exception as e:
                    print(f"获取{campus_area}实时POI失败，回退到本地数据: {e}")
            else:
                # 未指定区域，查询所有三个区域的实时POI并合并
                try:
                    all_pois = []
                    for area in ["学校食堂", "南门", "西门龙湖时代天街"]:
                        pois = await self.amap_service.search_nearby_pois(area)
                        if pois:
                            all_pois.extend(pois)
                    if all_pois:
                        return all_pois
                except Exception as e:
                    print(f"获取所有区域实时POI失败，回退到本地数据: {e}")

        # 回退到本地数据
        foods = self._local_foods.copy()
        if campus_area:
            foods = [f for f in foods if f.get("campus_area") == campus_area]

        # 标记为本地数据
        for food in foods:
            food["source"] = "本地备用数据"

        return foods

    async def recommend_foods(
        self,
        campus_area: Optional[str] = None,
        keywords: Optional[str] = None,
        taste: Optional[List[str]] = None,
        max_price: Optional[int] = None,
        max_distance: Optional[int] = None,
        min_rating: Optional[float] = None,
        meal_time: Optional[str] = None,
        exclude_allergens: Optional[List[str]] = None,
        limit: int = 10
    ) -> Dict:
        """
        推荐餐饮

        Args:
            campus_area: 校区区域
            keywords: 关键词搜索
            taste: 口味偏好
            max_price: 最高预算
            max_distance: 最远距离(米)
            min_rating: 最低评分
            meal_time: 用餐时段
            exclude_allergens: 排除的过敏原
            limit: 返回数量上限

        Returns:
            包含推荐列表和统计信息的字典
        """
        # 获取候选列表（优先实时POI）
        candidates = await self.get_foods(campus_area)
        total_candidates = len(candidates)

        # 关键词筛选
        if keywords:
            keywords_lower = keywords.lower()
            candidates = [
                f for f in candidates
                if keywords_lower in f.get("name", "").lower()
                or keywords_lower in f.get("cuisine", "").lower()
            ]

        # 口味筛选（仅对有口味标签的数据有效）
        if taste:
            candidates = [
                f for f in candidates
                if any(t in f.get("taste", []) for t in taste) or not f.get("taste")
            ]

        # 预算筛选
        if max_price is not None:
            candidates = [
                f for f in candidates
                if f.get("avg_price") is None or f.get("avg_price") <= max_price
            ]

        # 距离筛选
        if max_distance is not None:
            candidates = [
                f for f in candidates
                if f.get("distance") is not None and f.get("distance") <= max_distance
            ]

        # 评分筛选
        if min_rating is not None:
            candidates = [
                f for f in candidates
                if f.get("rating") is not None and f.get("rating") >= min_rating
            ]

        # 用餐时段筛选
        if meal_time:
            candidates = [
                f for f in candidates
                if meal_time in f.get("meal_time", []) or not f.get("meal_time")
            ]

        # 过敏原筛选
        if exclude_allergens:
            candidates = [
                f for f in candidates
                if not any(allergen in f.get("allergens", []) for allergen in exclude_allergens)
            ]

        # 排序：优先评分高、距离近、价格信息完整
        def sort_key(food):
            rating = food.get("rating") or 0
            distance = food.get("distance") or 9999
            has_price = 1 if food.get("avg_price") is not None else 0
            return (-rating, distance, -has_price)

        candidates.sort(key=sort_key)

        # 限制返回数量
        results = candidates[:limit]

        return {
            "results": results,
            "total_candidates": total_candidates,
            "filtered_count": len(candidates),
            "returned_count": len(results),
            "using_realtime": any(r.get("source") == "高德实时POI" for r in results)
        }
