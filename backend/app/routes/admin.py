"""区域配置管理路由"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict
import json
from pathlib import Path

router = APIRouter()

# 配置文件路径
CONFIG_FILE = Path(__file__).parent.parent / "services" / "area_config.json"


class AreaConfig(BaseModel):
    """区域配置模型"""
    location: str  # "经度,纬度"
    radius: int


class AreasUpdate(BaseModel):
    """区域配置更新请求"""
    areas: Dict[str, AreaConfig]


@router.get("/api/admin/areas")
async def get_areas():
    """获取当前区域配置"""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                areas = json.load(f)
        else:
            # 返回默认配置
            from app.services.amap_service import CAMPUS_AREAS
            areas = CAMPUS_AREAS

        return {"success": True, "areas": areas}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置失败: {str(e)}")


@router.post("/api/admin/areas")
async def update_areas(data: AreasUpdate):
    """更新区域配置"""
    try:
        # 验证数据格式
        areas_dict = {}
        for name, config in data.areas.items():
            # 验证location格式
            try:
                lon, lat = config.location.split(',')
                float(lon)
                float(lat)
            except:
                raise HTTPException(status_code=400, detail=f"区域 {name} 的坐标格式错误")

            # 验证半径
            if config.radius <= 0 or config.radius > 5000:
                raise HTTPException(status_code=400, detail=f"区域 {name} 的半径必须在1-5000米之间")

            areas_dict[name] = {
                "location": config.location,
                "radius": config.radius
            }

        # 保存到JSON文件
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(areas_dict, f, ensure_ascii=False, indent=2)

        # 动态更新内存中的配置
        from app.services import amap_service
        amap_service.CAMPUS_AREAS = areas_dict

        return {
            "success": True,
            "message": "区域配置已更新",
            "areas": areas_dict
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}")


@router.delete("/api/admin/areas/{area_name}")
async def delete_area(area_name: str):
    """删除指定区域"""
    try:
        if not CONFIG_FILE.exists():
            raise HTTPException(status_code=404, detail="配置文件不存在")

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            areas = json.load(f)

        if area_name not in areas:
            raise HTTPException(status_code=404, detail=f"区域 {area_name} 不存在")

        del areas[area_name]

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(areas, f, ensure_ascii=False, indent=2)

        # 更新内存配置
        from app.services import amap_service
        amap_service.CAMPUS_AREAS = areas

        return {"success": True, "message": f"区域 {area_name} 已删除"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
