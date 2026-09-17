"""AMap POI acquisition with explicit provenance and bounded per-region caching."""
import asyncio
import copy
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import httpx
from dotenv import load_dotenv

load_dotenv()
CONFIG_FILE = Path(__file__).parent / "area_config.json"
DEFAULT_AREAS = {
    "学校食堂": {"location": "103.9330,30.7560", "radius": 500},
    "南门": {"location": "103.9300,30.7540", "radius": 300},
    "西门龙湖时代天街": {"location": "103.9280,30.7640", "radius": 500},
}


def load_campus_areas():
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open(encoding="utf-8") as source:
                return json.load(source)
        except (OSError, ValueError):
            pass
    return copy.deepcopy(DEFAULT_AREAS)


CAMPUS_AREAS = load_campus_areas()


def safe_number(value, minimum=None, maximum=None, integer=False):
    """Upstream uses empty lists and strings for missing values; never invent zero."""
    if isinstance(value, (bool, list, dict, tuple)) or value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return int(number) if integer else number


def text_value(value):
    return value.strip() if isinstance(value, str) else ""


def boundary_distance(lon1, lat1, lon2, lat2):
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def point_in_polygon(lon, lat, vertices):
    inside = False
    for (x1, y1), (x2, y2) in zip(vertices, vertices[1:] + vertices[:1]):
        cross = (lon-x1)*(y2-y1)-(lat-y1)*(x2-x1)
        if abs(cross) < 1e-12 and min(x1,x2) <= lon <= max(x1,x2) and min(y1,y2) <= lat <= max(y1,y2):
            return True
        if (y1 > lat) != (y2 > lat) and lon < (x2-x1)*(lat-y1)/(y2-y1)+x1:
            inside = not inside
    return inside


def area_owner(poi, configs):
    matches = []
    try:
        lon, lat = map(float, poi["location"].split(","))
        for name, config in configs.items():
            if within_boundary(poi, config):
                x, y = map(float, config["location"].split(","))
                matches.append((boundary_distance(x, y, lon, lat), name))
    except (ValueError, TypeError, KeyError):
        return None
    return min(matches)[1] if matches else None


def within_boundary(poi, config):
    try:
        lon, lat = map(float, poi["location"].split(","))
        if not (math.isfinite(lon) and math.isfinite(lat)):
            return False
        if config.get("type") == "polygon":
            return point_in_polygon(lon, lat, config["path"])
        if config.get("type") == "rectangle":
            (w, s), (e, n) = config["bounds"]
            return w <= lon <= e and s <= lat <= n
        x, y = map(float, config["location"].split(","))
        return boundary_distance(x, y, lon, lat) <= config.get("radius", 500)
    except (KeyError, ValueError, TypeError):
        return False


class AmapService:
    def __init__(self):
        self.api_key = (os.getenv("AMAP_WEB_KEY") or "").strip()
        self.base_url = "https://restapi.amap.com/v3"
        self._cache = {}
        self._locks = {}

    async def search_nearby_pois(self, campus_area: str, keywords: str = "餐厅|美食") -> List[Dict]:
        if not self.api_key:
            return []
        area_config = CAMPUS_AREAS.get(campus_area)
        if not isinstance(area_config, dict) or not area_config.get("location"):
            return []
        # Include config in identity so region edits do not serve stale geometry.
        cache_key = (campus_area, keywords, json.dumps(CAMPUS_AREAS, sort_keys=True))
        cached = self._cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return copy.deepcopy(cached[1])
        lock = self._locks.setdefault(campus_area, asyncio.Lock())
        async with lock:
            cached = self._cache.get(cache_key)
            if cached and cached[0] > time.monotonic():
                return copy.deepcopy(cached[1])
            pois = await self._fetch_pois(campus_area, keywords, area_config)
            now = time.monotonic()
            self._cache = {key: value for key, value in self._cache.items() if value[0] > now}
            if CAMPUS_AREAS.get(campus_area) != area_config:
                return await self._fetch_pois(campus_area, keywords, CAMPUS_AREAS.get(campus_area, {}))
            self._cache[cache_key] = (now + (60 if pois else 15), copy.deepcopy(pois))
            return pois

    async def _fetch_pois(self, campus_area, keywords, area_config):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=2.0)) as client:
                response = await client.get(
                    f"{self.base_url}/place/around",
                    params={
                        "key": self.api_key,
                        "location": area_config["location"],
                        "keywords": keywords,
                        "types": "050000",
                        "radius": area_config.get("radius", 500),
                        "offset": 25,
                        "page": 1,
                        "extensions": "all",
                    },
                )
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict) or data.get("status") != "1":
                return []
            raw_pois = data.get("pois")
            if not isinstance(raw_pois, list):
                return []
            return [
                self._normalize_poi(poi, campus_area)
                for poi in raw_pois
                if isinstance(poi, dict) and text_value(poi.get("id")) and within_boundary(poi, area_config) and area_owner(poi, CAMPUS_AREAS) == campus_area
            ]
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            # Never log a request URL: it contains the API key.
            return []

    def _normalize_poi(self, poi: Dict, campus_area: str) -> Dict:
        location = text_value(poi.get("location")).split(",")
        longitude = safe_number(location[0], minimum=-180, maximum=180) if len(location) == 2 else None
        latitude = safe_number(location[1], minimum=-90, maximum=90) if len(location) == 2 else None
        biz_ext = poi.get("biz_ext")
        biz_ext = biz_ext if isinstance(biz_ext, dict) else {}
        avg_price = safe_number(biz_ext.get("cost"), minimum=0)
        rating = safe_number(biz_ext.get("rating"), minimum=0, maximum=5)
        # AMap commonly uses zero for unreported cost/rating.
        avg_price = avg_price if avg_price else None
        rating = rating if rating else None
        record_id = text_value(poi.get("id"))
        area_config = CAMPUS_AREAS.get(campus_area, {})
        return {
            "id": f"amap:{record_id}",
            "source_record_id": record_id,
            "name": text_value(poi.get("name")),
            "campus_area": campus_area,
            "cuisine": text_value(poi.get("type")).split(";")[-1],
            "taste": [],
            "avg_price": avg_price,
            "rating": rating,
            "distance": safe_number(poi.get("distance"), minimum=0, integer=True),
            "opening_hours": text_value(biz_ext.get("opentime")) or None,
            "is_open": None,
            "allergens": [],
            "meal_time": [],
            "latitude": latitude,
            "longitude": longitude,
            "address": text_value(poi.get("address")),
            "tel": text_value(poi.get("tel")),
            "source": "高德实时POI",
            "is_mock": False,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data_updated_at": None,
            "price_status": "reference" if avg_price is not None else "unknown",
            "allergen_status": "unknown",
            "opening_status": "unknown",
            "distance_basis": "area_center",
            "distance_origin": area_config.get("location"),
            "distance_note": "高德返回的区域查询中心参考距离；不是当前位置路线距离。",
            "availability": "live",
        }
