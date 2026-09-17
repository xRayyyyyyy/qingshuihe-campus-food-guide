"""Domain regressions: evidence handling, stable identities and bounded diagnostics."""
import asyncio
import copy
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.schemas.food import FoodFilters
from app.services.amap_service import AmapService
from app.services.food_service import FoodService


class FoodFilterTests(unittest.TestCase):
    def test_trim_and_reject_invalid_values(self):
        filters = FoodFilters(campus_area=" 学校食堂 ", keywords="  ", taste=[" 清淡 ", "", "清淡"])
        self.assertEqual(filters.campus_area, "学校食堂")
        self.assertIsNone(filters.keywords)
        self.assertEqual(filters.taste, ["清淡"])
        for patch in (
            {"made_up": True}, {"max_price": -1}, {"limit": 21}, {"min_rating": 6},
            {"campus_area": "不存在"}, {"max_distance": 1.5}, {"max_price": float("nan")},
            {"taste": "清淡"}, {"max_price": True},
        ):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                FoodFilters(**patch)


class FoodServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = FoodService()
        self.service.amap_service.api_key = ""

    async def test_plan_example_and_followup(self):
        filters = FoodFilters(campus_area="学校食堂", meal_time="晚餐", taste=["清淡"], max_price=15)
        first = await self.service.search(filters)
        self.assertEqual([food["id"] for food in first["results"]], ["local:2"])
        changed = FoodFilters(**{**filters.model_dump(), "max_price": 20, "exclude_ids": ["local:2"]})
        second = await self.service.search(changed)
        self.assertEqual([food["id"] for food in second["results"]], ["local:9"])
        self.assertEqual(first["results"][0]["source_record_id"], "2")
        self.assertIsNone(first["results"][0]["is_open"])
        self.assertIsNone(first["results"][0]["data_updated_at"])

    async def test_unknown_price_pending_but_known_violation_excluded(self):
        self.service._local_foods = [
            {"id": 1, "campus_area": "学校食堂", "avg_price": None, "rating": 4.8},
            {"id": 2, "campus_area": "学校食堂", "avg_price": None, "rating": 3},
            {"id": 3, "campus_area": "学校食堂", "avg_price": 10, "rating": 4.8},
            {"id": 4, "campus_area": "学校食堂", "avg_price": 30, "rating": 4.8},
        ]
        result = await self.service.search(FoodFilters(max_price=15, min_rating=4))
        self.assertEqual([food["id"] for food in result["results"]], ["local:3"])
        self.assertEqual([food["id"] for food in result["pending_results"]], ["local:1"])
        self.assertEqual(result["pending_results"][0]["unknown_constraints"], ["avg_price"])
        self.assertEqual(result["filter_counts"]["excluded"], 2)

    async def test_allergens_never_interpret_missing_as_safe(self):
        result = await self.service.search(FoodFilters(exclude_allergens=["奶制品"], limit=20))
        self.assertEqual(result["results"], [])
        self.assertTrue(result["pending_results"])
        self.assertTrue(all("allergens" in food["unknown_constraints"] for food in result["pending_results"]))
        self.assertTrue(all("奶制品" not in food["allergens"] for food in result["pending_results"]))
        self.assertEqual(result["filter_counts"]["excluded"], 5)
        self.assertIn("过敏安全", " ".join(result["unknowns"]))

    async def test_all_positive_tastes_and_no_spicy_tags(self):
        result = await self.service.search(FoodFilters(taste=["家常", "清淡"]))
        self.assertEqual([food["id"] for food in result["results"]], ["local:2"])
        result = await self.service.search(FoodFilters(exclude_taste=["辣"], exclude_cuisines=["火锅"], limit=20))
        self.assertTrue(result["results"])
        self.assertTrue(all(not any("辣" in tag for tag in food["taste"]) for food in result["results"]))
        self.service._local_foods[0]["taste"] = []
        result = await self.service.search(FoodFilters(exclude_taste=["辣"], limit=20))
        self.assertIn("local:1", [food["id"] for food in result["pending_results"]])
        self.assertNotIn("local:1", [food["id"] for food in result["results"]])

    async def test_diagnostics_are_counterfactual_and_preserve_exclusions(self):
        filters = FoodFilters(campus_area="学校食堂", meal_time="晚餐", taste=["清淡"], max_price=15, min_rating=4.5)
        before = copy.deepcopy(filters.model_dump())
        suggestions = await self.service.suggest_changes(filters)
        self.assertEqual(filters.model_dump(), before)
        self.assertEqual([item["id"] for item in suggestions], ["lower_rating"])
        self.assertEqual(suggestions[0]["count"], 1)
        for item in suggestions:
            proposed = FoodFilters(**{**before, **item["changes"]})
            actual = await self.service.search(proposed)
            self.assertEqual(actual["filtered_count"], item["count"])
        protected = FoodFilters(exclude_taste=["辣"], exclude_allergens=["花生"], max_price=1)
        self.assertEqual(await self.service.suggest_changes(protected), [])

    async def test_local_records_are_not_mutated(self):
        before = copy.deepcopy(self.service._local_foods)
        foods = await self.service.get_foods()
        foods[0]["taste"].append("外部修改")
        self.assertEqual(self.service._local_foods, before)
        self.assertEqual(len({food["id"] for food in foods}), 20)

    async def test_one_failed_region_does_not_hide_another(self):
        self.service.amap_service.api_key = "test-only"
        started = set()
        all_started = asyncio.Event()

        async def search(area):
            started.add(area)
            if len(started) == 3:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), 0.5)
            if area == "南门":
                raise RuntimeError("fake upstream failure")
            return [self.service.amap_service._normalize_poi({"id": area, "name": area}, area)]

        self.service.amap_service.search_nearby_pois = search
        configs = {name:{"location":location,"radius":100} for name,location in
                   [("学校食堂","103,30"),("南门","104,30"),("西门龙湖时代天街","105,30")]}
        self.service._local_foods = [
            {"id":i,"campus_area":"南门","longitude":104,"latitude":30} for i in range(4)
        ] + [{"id":99,"campus_area":"南门","longitude":105,"latitude":30}]
        with patch("app.services.amap_service.CAMPUS_AREAS", configs):
            foods = await self.service.get_foods()
        self.assertEqual(len(started), 3)
        self.assertEqual(len([food for food in foods if not food["is_mock"]]), 2)
        fallback = [food for food in foods if food["is_mock"]]
        self.assertEqual(len(fallback), 4)
        self.assertTrue(all(food["campus_area"] == "南门" for food in fallback))
        self.assertTrue(all(food["availability"] == "amap_fallback" for food in fallback))

    async def test_missing_sort_values_go_last_and_zero_distance_is_valid(self):
        self.service._local_foods = [
            {"id": 1, "campus_area": "学校食堂", "avg_price": None, "distance": None},
            {"id": 2, "campus_area": "学校食堂", "avg_price": 5, "distance": 0},
        ]
        for sort_by in ("price", "reference_distance"):
            result = await self.service.search(FoodFilters(sort_by=sort_by))
            self.assertEqual([food["id"] for food in result["results"]], ["local:2", "local:1"])


class AmapTests(unittest.IsolatedAsyncioTestCase):
    async def test_normalization_preserves_identity_and_does_not_invent_facts(self):
        service = AmapService()
        poi = service._normalize_poi({
            "id": "B001", "location": "bad,NaN", "distance": [],
            "biz_ext": {"cost": [], "rating": "NaN", "opentime": []},
        }, "学校食堂")
        self.assertEqual(poi["id"], "amap:B001")
        for key in ("avg_price", "rating", "distance", "is_open", "latitude", "longitude", "data_updated_at"):
            self.assertIsNone(poi[key], key)
        self.assertEqual(poi["meal_time"], [])
        zero_cost = service._normalize_poi({"id": "B002", "biz_ext": {"cost": "0", "rating": "0"}}, "南门")
        self.assertIsNone(zero_cost["avg_price"])
        self.assertIsNone(zero_cost["rating"])

    async def test_cache_coalesces_concurrent_calls_and_returns_copies(self):
        service = AmapService()
        service.api_key = "test-only"
        requests = []

        async def fetch(area, keywords, config):
            requests.append(area)
            await asyncio.sleep(0)
            return [{"id": "amap:1", "name": "原始名称"}]

        service._fetch_pois = fetch
        first, second = await asyncio.gather(service.search_nearby_pois("南门"), service.search_nearby_pois("南门"))
        self.assertEqual(requests, ["南门"])
        first[0]["name"] = "修改"
        self.assertEqual(second[0]["name"], "原始名称")
        self.assertEqual((await service.search_nearby_pois("南门"))[0]["name"], "原始名称")


if __name__ == "__main__":
    unittest.main()
