"""Campus food API: deterministic recommendations and a bounded dialogue agent."""
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from app.agents.food_agent import FoodAgent
from app.routes.admin import router as admin_router
from app.routes.chat import router as chat_router
from app.schemas.food import FoodFilters
from app.services.food_service import FoodService

app = FastAPI(title="校园觅食 Agent", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)
food_service = FoodService()
app.state.food_service = food_service
app.state.food_agent = FoodAgent(food_service)
app.include_router(admin_router)
app.include_router(chat_router)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "校园美食推荐助手运行正常"}


@app.get("/api/foods")
async def get_foods(campus_area: str | None = None):
    try:
        filters = FoodFilters(campus_area=campus_area)
    except ValidationError:
        raise HTTPException(422, "校区区域无效") from None
    foods = await food_service.get_foods(filters.campus_area)
    return {"foods": foods, "count": len(foods)}


@app.get("/api/recommend")
async def recommend_foods(
    campus_area: str | None = None,
    keywords: str | None = Query(None, max_length=100),
    taste: str | None = Query(None, max_length=300),
    max_price: float | None = Query(None, ge=0, le=10000),
    max_distance: int | None = Query(None, ge=0, le=100000),
    min_rating: float | None = Query(None, ge=0, le=5),
    meal_time: str | None = None,
    exclude_allergens: str | None = Query(None, max_length=300),
    exclude_taste: str | None = Query(None, max_length=300),
    exclude_cuisines: str | None = Query(None, max_length=300),
    exclude_ids: str | None = Query(None, max_length=3000),
    sort_by: Literal["rating", "price", "reference_distance"] = "rating",
    limit: int = Query(10, ge=1, le=20),
):
    def split(value):
        return [item.strip() for item in value.split(",") if item.strip()] if value else []
    try:
        filters = FoodFilters(
            campus_area=campus_area, keywords=keywords, taste=split(taste), max_price=max_price,
            max_distance=max_distance, min_rating=min_rating, meal_time=meal_time,
            exclude_allergens=split(exclude_allergens), exclude_taste=split(exclude_taste),
            exclude_cuisines=split(exclude_cuisines), exclude_ids=split(exclude_ids),
            sort_by=sort_by, limit=limit,
        )
    except ValidationError:
        raise HTTPException(422, "筛选条件无效") from None
    return await food_service.search(filters)


@app.get("/")
async def root():
    return {"message": "校园觅食 Agent API", "docs": "/docs", "health": "/api/health"}
