"""FastAPI主应用"""
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
from app.services.food_service import FoodService

app = FastAPI(title="校园美食推荐助手")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化服务
food_service = FoodService()

# 导入管理路由
from app.routes.admin import router as admin_router
app.include_router(admin_router)


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "message": "校园美食推荐助手运行正常"}


@app.get("/api/foods")
async def get_foods(
    campus_area: Optional[str] = Query(None, description="校区区域")
):
    """
    获取餐饮列表

    Args:
        campus_area: 学校食堂|南门|西门龙湖时代天街
    """
    foods = await food_service.get_foods(campus_area)
    return {
        "foods": foods,
        "count": len(foods)
    }


@app.get("/api/recommend")
async def recommend_foods(
    campus_area: Optional[str] = Query(None, description="校区区域"),
    keywords: Optional[str] = Query(None, description="关键词搜索"),
    taste: Optional[str] = Query(None, description="口味偏好，逗号分隔"),
    max_price: Optional[int] = Query(None, description="最高预算"),
    max_distance: Optional[int] = Query(None, description="最远距离(米)"),
    min_rating: Optional[float] = Query(None, description="最低评分"),
    meal_time: Optional[str] = Query(None, description="用餐时段"),
    exclude_allergens: Optional[str] = Query(None, description="排除过敏原，逗号分隔"),
    limit: int = Query(10, description="返回数量上限")
):
    """
    推荐餐饮

    Args:
        campus_area: 学校食堂|南门|西门龙湖时代天街
        keywords: 搜索关键词
        taste: 口味偏好列表
        max_price: 最高预算
        max_distance: 最远距离
        min_rating: 最低评分
        meal_time: 早餐|午餐|晚餐|夜宵
        exclude_allergens: 排除的过敏原列表
        limit: 返回数量
    """
    # 解析列表参数
    taste_list = taste.split(",") if taste else None
    allergens_list = exclude_allergens.split(",") if exclude_allergens else None

    result = await food_service.recommend_foods(
        campus_area=campus_area,
        keywords=keywords,
        taste=taste_list,
        max_price=max_price,
        max_distance=max_distance,
        min_rating=min_rating,
        meal_time=meal_time,
        exclude_allergens=allergens_list,
        limit=limit
    )

    return result


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "欢迎使用校园美食推荐助手API",
        "docs": "/docs",
        "health": "/api/health"
    }
