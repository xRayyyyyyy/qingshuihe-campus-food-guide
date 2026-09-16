# 清水河校区校园美食推荐助手

电子科技大学清水河校区的校园美食推荐应用，支持按区域、预算、口味、距离等多维度筛选推荐餐饮。

## 功能特性

- ✅ 餐饮数据展示：20条示例数据（学校食堂13条、南门4条、西门龙湖时代天街3条）
- ✅ 搜索与筛选：支持关键词、校区区域、用餐时段、口味、预算、距离、评分、忌口等筛选
- ✅ 个性化推荐：根据多条件返回Top 10推荐结果
- ✅ 详情查看：点击卡片查看餐厅详细信息
- ✅ 地图展示：高德地图标记餐厅位置
- ✅ 异常处理：友好处理无结果、空输入等情况
- ✅ 数据说明：明确标注本地备用数据或高德实时POI

## 技术栈

**后端**
- FastAPI
- Python 3.8+
- 高德地图API（可选）

**前端**
- Vue 3
- Vite
- 高德地图JS API

## 项目结构

```
.
├── backend/
│   ├── app/
│   │   ├── data/
│   │   │   └── foods.json          # 本地餐饮数据
│   │   ├── services/
│   │   │   ├── amap_service.py     # 高德地图服务
│   │   │   └── food_service.py     # 餐饮推荐服务
│   │   └── main.py                 # FastAPI主应用
│   ├── .env                        # 后端配置（需创建）
│   └── requirements.txt            # Python依赖
│
├── frontend/
│   ├── src/
│   │   ├── App.vue                 # 主组件
│   │   ├── main.js                 # 入口文件
│   │   └── style.css               # 样式
│   ├── index.html
│   ├── vite.config.js
│   ├── package.json
│   └── .env.local                  # 前端配置（需创建）
│
└── README.md
```

## 快速开始

### 1. 配置环境变量

**后端配置** - 复制 `backend/.env.example` 为 `backend/.env`，填入高德Web服务Key（可选）：

```env
AMAP_WEB_KEY=your_amap_web_service_key
```

**前端配置** - 编辑 `frontend/.env.local`，填入API地址和高德JS Key：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_AMAP_JS_KEY=your_amap_js_web_key
```

同时修改 `frontend/index.html` 中的高德地图script标签，替换YOUR_AMAP_JS_KEY。

### 2. 安装依赖

**后端**：
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**前端**：
```bash
cd frontend
npm install
```

### 3. 启动服务

**后端**：
```bash
cd backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**前端**：
```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

### 4. 访问应用

打开浏览器访问：http://127.0.0.1:5173

## API文档

后端启动后访问 http://127.0.0.1:8000/docs 查看完整API文档。

### 主要接口

- `GET /api/health` - 健康检查
- `GET /api/foods?campus_area={区域}` - 获取餐饮列表
- `GET /api/recommend?...` - 获取推荐结果

## 数据说明

### 本地模式
如果未配置高德API Key，应用使用本地模拟数据（`backend/app/data/foods.json`），共20条记录。

### 实时模式
配置高德API Key后，应用优先从高德地图获取实时POI数据。高德API失败时自动回退到本地数据。

**注意**：
- 高德返回的价格、评分、营业时间可能不完整，会显示"暂无"
- 口味标签和过敏原信息仅本地数据支持
- 数据来源会在界面明确标注

## 作业提交说明

本项目为"Vibe Coding编程思维"课程作业。提交材料包括：

1. **系统截图**（3-5张）
2. **AI原始日志**（完整交互记录）
3. **AI日志索引**（Excel/CSV格式）

详细要求见课程文档。

## 版权声明

本项目仅用于课程学习，不得用于商业用途。

## 开发时间

2026年9月
