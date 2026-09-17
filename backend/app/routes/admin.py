"""Local area editor and validated, persistent query boundaries."""
import json
import math
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, model_validator

router = APIRouter()
ROOT = Path(__file__).resolve().parents[3]
CONFIG_FILE = Path(__file__).parent.parent / "services" / "area_config.json"
NAMES = {"学校食堂", "南门", "西门龙湖时代天街"}

class AreaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    location: str
    radius: int = Field(ge=1, le=5000)
    type: Literal["circle", "rectangle", "polygon"] = "circle"
    bounds: tuple[tuple[float, float], tuple[float, float]] | None = None

    path: list[tuple[float, float]] | None = Field(default=None, min_length=3, max_length=100)

    @model_validator(mode="after")
    def validate_geometry(self):
        lon, lat = map(float, self.location.split(","))
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("经纬度无效")
        if self.type == "polygon":
            if not self.path or self.bounds is not None:
                raise ValueError("多边形需要至少三个顶点，不能包含矩形边界")
            if any(not (-180 <= x <= 180 and -90 <= y <= 90) for x,y in self.path):
                raise ValueError("多边形坐标无效")
            if len(set(self.path)) < 3:
                raise ValueError("多边形需要三个不同顶点")
            signed = sum(x1*y2-x2*y1 for (x1,y1),(x2,y2) in zip(self.path,self.path[1:]+self.path[:1]))
            if abs(signed) < 1e-10:
                raise ValueError("多边形面积必须大于零")
            lon = (min(x for x,y in self.path)+max(x for x,y in self.path))/2
            lat = (min(y for x,y in self.path)+max(y for x,y in self.path))/2
            from app.services.amap_service import boundary_distance
            self.radius = math.ceil(max(boundary_distance(lon,lat,x,y) for x,y in self.path))
            if not 1 <= self.radius <= 5000:
                raise ValueError("多边形覆盖半径必须在 1–5000 米")
        elif self.path is not None:
            raise ValueError("非多边形不能包含顶点")
        if self.type == "rectangle":
            if self.bounds is None:
                raise ValueError("矩形必须包含西南和东北坐标")
            (west, south), (east, north) = self.bounds
            if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
                raise ValueError("矩形边界无效")
            lon, lat = (west + east) / 2, (south + north) / 2
            from app.services.amap_service import boundary_distance
            self.radius = math.ceil(max(boundary_distance(lon, lat, x, y) for x in (west, east) for y in (south, north)))
            if not 1 <= self.radius <= 5000:
                raise ValueError("区域过大或过小，覆盖半径必须在 1–5000 米")
        elif self.bounds is not None:
            raise ValueError("圆形不能包含矩形边界")
        self.location = f"{lon:.6f},{lat:.6f}"
        return self

class AreasUpdate(BaseModel):
    areas: dict[str, AreaConfig]

    @model_validator(mode="after")
    def names(self):
        if not self.areas or not set(self.areas) <= NAMES:
            raise ValueError("至少保留一个区域，名称须为学校食堂、南门或西门龙湖时代天街")
        return self

@router.get("/area-config", include_in_schema=False)
async def editor():
    return FileResponse(ROOT / "区域配置工具.html", media_type="text/html", headers={"Cache-Control": "no-store"})

@router.get("/api/admin/map-config")
async def map_config():
    values = dotenv_values(ROOT / "frontend" / ".env.local")
    return {"key": values.get("VITE_AMAP_JS_KEY", ""), "securityJsCode": values.get("VITE_AMAP_SECURITY_CODE", "")}

@router.get("/api/admin/areas")
async def get_areas():
    from app.services import amap_service
    return {"success": True, "areas": amap_service.CAMPUS_AREAS}

def persist(areas):
    from app.services import amap_service
    temp = CONFIG_FILE.with_suffix(".json.tmp")
    try:
        temp.write_text(json.dumps(areas, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(CONFIG_FILE)
    except OSError:
        raise HTTPException(500, "区域配置写入失败") from None
    amap_service.CAMPUS_AREAS = areas

@router.post("/api/admin/areas")
async def update_areas(data: AreasUpdate):
    areas = {name: area.model_dump(exclude_none=True) for name, area in data.areas.items()}
    persist(areas)
    return {"success": True, "areas": areas}

@router.delete("/api/admin/areas/{area_name}")
async def delete_area(area_name: str):
    from app.services import amap_service
    areas = dict(amap_service.CAMPUS_AREAS)
    if area_name not in areas:
        raise HTTPException(404, "区域不存在")
    if len(areas) <= 1:
        raise HTTPException(400, "至少保留一个区域")
    del areas[area_name]
    persist(areas)
    return {"success": True, "areas": areas}
