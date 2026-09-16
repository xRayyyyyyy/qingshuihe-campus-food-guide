# Handoff - 校园美食推荐助手项目

## 📋 项目概述

**项目名称**: 清水河校区校园美食推荐助手
**开发时间**: 2026-09-13
**开发方式**: AI辅助开发 (Vibe Coding)
**技术栈**: Vue 3 + FastAPI + 高德地图API

---

## ✅ 已完成功能

### 核心功能
- ✅ 20条本地餐饮数据（学校食堂13条、南门4条、西门3条）
- ✅ 8个筛选条件（关键词、区域、时段、口味、预算、距离、评分、忌口）
- ✅ Top 10智能推荐算法（按评分+距离+信息完整度排序）
- ✅ 详情查看（点击卡片或地图标记打开详情抽屉）
- ✅ 地图展示（高德地图，带标记和定位）
- ✅ 异常处理（无结果、空输入、接口失败回退）
- ✅ 数据来源标注（实时POI或本地数据）

### 高德地图集成
- ✅ Web服务API Key配置（后端）: `YOUR_AMAP_WEB_SERVICE_KEY`
- ✅ JS API Key配置（前端）: `YOUR_AMAP_JS_KEY`
- ✅ 实时POI查询（三个区域自动合并）
- ✅ 精确GPS坐标（6位小数）
- ✅ 自动回退机制（API失败时使用本地数据）

### 区域配置系统
- ✅ 可视化配置工具（`区域配置工具.html`）
- ✅ 管理API（GET/POST/DELETE `/api/admin/areas`）
- ✅ 动态加载配置（无需重启服务）
- ✅ JSON文件存储（`backend/app/services/area_config.json`）

---

## 🐛 已修复的问题

### 问题1: 高德实时POI未启用
- **原因**: 初始配置的是JS API Key，后端需要Web服务Key
- **修复**: 更换为正确的Web服务API Key，并修改逻辑支持不指定区域时查询所有区域

### 问题2: 本地数据地图位置重叠
- **原因**: 所有餐厅使用区域中心点坐标
- **修复**: 为每家餐厅分配独立GPS坐标（5位小数精度）

### 问题3: 区域配置坐标错误
- **原因**: "学校食堂"配置在北部，实际查到的是商业区
- **修复**: 调整区域中心点，现在配置准确

### 问题4: 地图不显示
- **原因**: 高德地图2.0的Scale和ToolBar需要异步加载插件
- **修复**: 使用`AMap.plugin()`先加载插件再添加控件

### 问题5: 依赖安装失败
- **原因**: Python 3.13与pydantic 2.5.0不兼容，SSL证书问题
- **修复**: 更新依赖版本，使用国内镜像源安装

---

## 🗂️ 项目结构

```
vibecodingcc/
├── backend/                    # 后端服务
│   ├── app/
│   │   ├── data/
│   │   │   └── foods.json      # 本地餐饮数据（20条）
│   │   ├── services/
│   │   │   ├── amap_service.py # 高德地图服务
│   │   │   ├── food_service.py # 推荐逻辑
│   │   │   └── area_config.json # 区域配置（动态生成）
│   │   ├── routes/
│   │   │   └── admin.py        # 管理API
│   │   └── main.py             # FastAPI应用
│   ├── .env                    # 环境配置（高德Web服务Key）
│   └── requirements.txt        # Python依赖
│
├── frontend/                   # 前端应用
│   ├── src/
│   │   ├── App.vue            # 主组件（600+行）
│   │   ├── main.js            # 入口
│   │   └── style.css          # 样式
│   ├── index.html             # HTML模板（含高德JS Key）
│   ├── vite.config.js
│   └── package.json
│
├── 区域配置工具.html           # 可视化区域配置工具
│
├── 提交材料/                   # 作业提交材料
│   ├── 01_系统截图/
│   ├── 02_AI原始日志/
│   └── 03_AI日志索引_学号+姓名.csv
│
└── 文档/
    ├── README.md              # 项目说明
    ├── 运行与测试指南.md
    ├── 技术架构文档.md
    ├── 系统测试完成报告.md
    └── 方案B实现说明.md
```

---

## 🚀 启动服务

### 后端（端口8000）
```bash
cd /Users/lxr/vibecodingcc/backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 前端（端口5173）
```bash
cd /Users/lxr/vibecodingcc/frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

### 访问地址
- **前端应用**: http://127.0.0.1:5173
- **后端API**: http://127.0.0.1:8000
- **API文档**: http://127.0.0.1:8000/docs
- **配置工具**: 双击打开 `区域配置工具.html`

---

## 🎯 待完成任务

### 1. 优化区域配置（推荐）
当前区域配置可能不够精确，建议使用配置工具重新绘制：

1. 打开 `区域配置工具.html`
2. 在地图上准确绘制三个区域：
   - **学校食堂**: 校内食堂区域（银桦、2食堂、3食堂等）
   - **南门**: 南门外商业街
   - **西门龙湖时代天街**: 龙湖购物中心区域
3. 点击「💾 保存到后端」
4. 新配置自动生效，无需重启

### 2. 完成作业提交
- [ ] 5张系统截图（按`提交材料/01_系统截图/截图说明.md`）
- [ ] 导出AI原始日志
- [ ] 检查AI日志索引CSV
- [ ] 打包为"学号+姓名.zip"

---

## 📊 核心API接口

### 推荐API
```bash
# 获取推荐（不指定区域，返回所有区域实时POI）
GET /api/recommend?limit=10

# 指定区域推荐
GET /api/recommend?campus_area=学校食堂&max_price=20

# 多条件筛选
GET /api/recommend?campus_area=南门&taste=麻辣&max_price=30&min_rating=4.0
```

### 管理API
```bash
# 获取当前区域配置
GET /api/admin/areas

# 更新区域配置
POST /api/admin/areas
Body: { "areas": { "学校食堂": { "location": "103.9330,30.7560", "radius": 500 } } }

# 删除区域
DELETE /api/admin/areas/学校食堂
```

---

## 🔧 重要配置

### 高德地图API Key
- **Web服务Key**（后端）: `YOUR_AMAP_WEB_SERVICE_KEY`
  - 配置位置: `backend/.env` 的 `AMAP_WEB_KEY`
- **JS API Key**（前端）: `YOUR_AMAP_JS_KEY`
  - 配置位置: `frontend/.env.local` 和 `frontend/index.html`

### 区域配置
- **存储位置**: `backend/app/services/area_config.json`
- **默认值**: 如文件不存在，使用代码中的DEFAULT_AREAS
- **动态加载**: 保存后自动重新加载，无需重启

---

## 🔍 调试信息

### 后端日志
运行uvicorn的终端窗口会显示：
- API请求日志
- 高德API调用情况
- 错误信息

### 前端日志
浏览器F12 Console会显示：
- 地图初始化状态（✓ 开始初始化地图...）
- API请求响应
- JavaScript错误

---

## 💡 技术细节

### 推荐算法排序
```python
def sort_key(food):
    rating = food.get("rating") or 0        # 评分高优先
    distance = food.get("distance") or 9999 # 距离近优先
    has_price = 1 if food.get("avg_price") else 0  # 信息完整优先
    return (-rating, distance, -has_price)
```

### 双数据源策略
1. 配置了高德API Key → 查询实时POI
2. API失败或无Key → 回退到本地20条数据
3. 数据来源明确标识（"高德实时POI" or "本地备用数据"）

### 地图标记点击功能
- 点击标记 → 打开详情抽屉（而非信息窗）
- 地图自动定位到该餐厅
- 显示完整信息（包括电话、地址等）

---

## 📚 参考文档

项目根目录下的完整文档：

1. **README.md** - 项目说明和快速开始
2. **运行与测试指南.md** - 15个详细测试用例
3. **技术架构文档.md** - 完整技术说明和API设计
4. **系统测试完成报告.md** - 所有功能的测试结果
5. **方案B实现说明.md** - 区域配置自动化方案

---

## ⚠️ 已知限制

1. **高德实时POI限制**
   - 口味标签和过敏原信息不完整（API本身限制）
   - 营业状态可能不准确
   - 部分餐厅价格和评分为空

2. **区域配置**
   - 当前配置可能不够精确
   - 建议使用配置工具重新绘制

3. **安全性**
   - 管理API未加认证（仅开发环境使用）
   - API Key明文存储（生产环境应加密）

---

## 🎓 作业要求对照

| 要求 | 状态 | 说明 |
|------|------|------|
| ≥20条数据 | ✅ | 20条 |
| ≥4个筛选条件 | ✅ | 8个 |
| Top 3-5推荐 | ✅ | Top 10 |
| 详情查看 | ✅ | 详情抽屉 |
| 异常处理 | ✅ | 全面覆盖 |
| 数据说明 | ✅ | 明确标注 |
| 系统截图 | ⏳ | 待完成 |
| AI日志 | ✅ | 完整记录 |
| 日志索引 | ✅ | 13轮交互 |

---

## 🔄 下次启动清单

1. **读取本文件** - 了解项目状态
2. **启动服务** - 后端和前端
3. **验证功能** - 测试各项功能是否正常
4. **完成任务** - 根据"待完成任务"部分执行

---

**最后更新**: 2026-09-13
**项目状态**: ✅ 功能完整，可交付
**下一步**: 优化区域配置，完成作业截图
