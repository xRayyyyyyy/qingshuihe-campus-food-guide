"""高德地图服务模块"""
import os
import json
import httpx
from typing import Dict, List, Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# 配置文件路径
CONFIG_FILE = Path(__file__).parent / "area_config.json"

# 默认区域配置
DEFAULT_AREAS = {
    "学校食堂": {
        "location": "103.9330,30.7560",
        "radius": 500
    },
    "南门": {
        "location": "103.9300,30.7540",
        "radius": 300
    },
    "西门龙湖时代天街": {
        "location": "103.9280,30.7640",
        "radius": 500
    }
}

# 加载配置
def load_campus_areas():
    """从文件加载区域配置，如果文件不存在则使用默认配置"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"加载区域配置失败: {e}，使用默认配置")
    return DEFAULT_AREAS.copy()

# 三个业务区域的中心点和搜索半径
CAMPUS_AREAS = load_campus_areas()


class AmapService:
    """高德地图API服务类"""

    def __init__(self):
        self.api_key = os.getenv("AMAP_WEB_KEY")
        self.base_url = "https://restapi.amap.com/v3"

    async def search_nearby_pois(self, campus_area: str, keywords: str = "餐厅|美食") -> List[Dict]:
        """
        周边搜索餐饮POI

        Args:
            campus_area: 校区区域名称
            keywords: 搜索关键词

        Returns:
            标准化的POI列表
        """
        if not self.api_key:
            return []

        area_config = CAMPUS_AREAS.get(campus_area)
        if not area_config:
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/place/around",
                    params={
                        "key": self.api_key,
                        "location": area_config["location"],
                        "keywords": keywords,
                        "types": "050000|060000",  # 餐饮服务类型
                        "radius": area_config["radius"],
                        "offset": 25,
                        "page": 1,
                        "extensions": "all"
                    }
                )

                if response.status_code != 200:
                    return []

                data = response.json()
                if data.get("status") != "1" or not data.get("pois"):
                    return []

                # 标准化POI数据
                return [self._normalize_poi(poi, campus_area) for poi in data["pois"]]

        except Exception as e:
            print(f"高德API调用失败: {e}")
            return []

    def _normalize_poi(self, poi: Dict, campus_area: str) -> Dict:
        """
        将高德POI标准化为统一格式

        Args:
            poi: 高德返回的原始POI数据
            campus_area: 所属校区区域

        Returns:
            标准化的餐厅数据
        """
        # 解析经纬度
        location = poi.get("location", "").split(",")
        longitude = float(location[0]) if len(location) > 0 else 0
        latitude = float(location[1]) if len(location) > 1 else 0

        # 解析距离
        distance = int(poi.get("distance", "0"))

        # 解析扩展信息
        biz_ext = poi.get("biz_ext", {})

        # 尝试解析价格（人均）
        cost = biz_ext.get("cost")
        avg_price = None
        if cost:
            try:
                avg_price = int(cost)
            except (ValueError, TypeError):
                pass

        # 尝试解析评分
        rating = biz_ext.get("rating")
        if rating:
            try:
                rating = float(rating)
            except (ValueError, TypeError):
                rating = None

        # 营业时间
        opentime = biz_ext.get("opentime", "营业时间以高德地图为准")

        return {
            "name": poi.get("name", ""),
            "campus_area": campus_area,
            "cuisine": poi.get("type", "").split(";")[-1] if poi.get("type") else "餐饮",
            "taste": [],
            "avg_price": avg_price,
            "rating": rating,
            "distance": distance,
            "opening_hours": opentime,
            "is_open": None,  # 高德周边搜索不提供实时营业状态
            "allergens": [],
            "meal_time": ["午餐", "晚餐"],  # 默认
            "latitude": latitude,
            "longitude": longitude,
            "address": poi.get("address", ""),
            "tel": poi.get("tel", ""),
            "source": "高德实时POI"
        }
