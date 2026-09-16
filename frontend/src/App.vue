<template>
  <div class="app-container">
    <header class="app-header">
      <h1>🍜 清水河校区美食推荐助手</h1>
      <p class="data-notice">{{ dataNotice }}</p>
    </header>

    <div class="main-content">
      <!-- 左侧筛选面板 -->
      <aside class="filter-panel">
        <h2>筛选条件</h2>

        <div class="filter-group">
          <label>校区区域</label>
          <select v-model="filters.campusArea" @change="handleFilterChange">
            <option value="">全部区域</option>
            <option value="学校食堂">学校食堂</option>
            <option value="南门">南门</option>
            <option value="西门龙湖时代天街">西门龙湖时代天街</option>
          </select>
        </div>

        <div class="filter-group">
          <label>关键词搜索</label>
          <input
            v-model="filters.keywords"
            type="text"
            placeholder="搜索餐厅或菜品"
            @input="handleFilterChange"
          />
        </div>

        <div class="filter-group">
          <label>用餐时段</label>
          <select v-model="filters.mealTime" @change="handleFilterChange">
            <option value="">不限</option>
            <option value="早餐">早餐</option>
            <option value="午餐">午餐</option>
            <option value="晚餐">晚餐</option>
            <option value="夜宵">夜宵</option>
          </select>
        </div>

        <div class="filter-group">
          <label>口味偏好</label>
          <div class="checkbox-group">
            <label><input type="checkbox" value="清淡" v-model="filters.taste" @change="handleFilterChange"> 清淡</label>
            <label><input type="checkbox" value="家常" v-model="filters.taste" @change="handleFilterChange"> 家常</label>
            <label><input type="checkbox" value="微辣" v-model="filters.taste" @change="handleFilterChange"> 微辣</label>
            <label><input type="checkbox" value="麻辣" v-model="filters.taste" @change="handleFilterChange"> 麻辣</label>
            <label><input type="checkbox" value="重口味" v-model="filters.taste" @change="handleFilterChange"> 重口味</label>
            <label><input type="checkbox" value="甜" v-model="filters.taste" @change="handleFilterChange"> 甜</label>
          </div>
        </div>

        <div class="filter-group">
          <label>预算上限（元）</label>
          <input
            v-model.number="filters.maxPrice"
            type="number"
            placeholder="不限"
            @input="handleFilterChange"
          />
        </div>

        <div class="filter-group">
          <label>最远距离（米）</label>
          <input
            v-model.number="filters.maxDistance"
            type="number"
            placeholder="不限"
            @input="handleFilterChange"
          />
        </div>

        <div class="filter-group">
          <label>最低评分</label>
          <select v-model.number="filters.minRating" @change="handleFilterChange">
            <option :value="null">不限</option>
            <option :value="3.0">3.0分以上</option>
            <option :value="4.0">4.0分以上</option>
            <option :value="4.5">4.5分以上</option>
          </select>
        </div>

        <div class="filter-group">
          <label>忌口/过敏原</label>
          <div class="checkbox-group">
            <label><input type="checkbox" value="花椒" v-model="filters.excludeAllergens" @change="handleFilterChange"> 花椒</label>
            <label><input type="checkbox" value="小麦" v-model="filters.excludeAllergens" @change="handleFilterChange"> 小麦</label>
            <label><input type="checkbox" value="奶制品" v-model="filters.excludeAllergens" @change="handleFilterChange"> 奶制品</label>
          </div>
        </div>

        <button class="btn-primary" @click="getRecommendations">获取推荐</button>
        <button class="btn-secondary" @click="resetFilters">重置</button>
      </aside>

      <!-- 右侧结果展示 -->
      <main class="results-section">
        <div v-if="loading" class="loading">加载中...</div>

        <div v-else-if="error" class="error-message">
          {{ error }}
        </div>

        <div v-else-if="recommendations.length === 0" class="no-results">
          <p>😔 没有找到符合条件的餐厅</p>
          <p>建议：</p>
          <ul>
            <li>放宽预算或距离限制</li>
            <li>减少筛选条件</li>
            <li>尝试其他校区区域</li>
          </ul>
        </div>

        <div v-else>
          <div class="results-header">
            <h2>推荐结果</h2>
            <p class="result-stats">
              找到 {{ filteredCount }} 家餐厅，显示前 {{ recommendations.length }} 家
              <span v-if="usingRealtime" class="badge-realtime">高德实时POI</span>
              <span v-else class="badge-local">本地备用数据</span>
            </p>
          </div>

          <div class="food-grid">
            <div
              v-for="(food, index) in recommendations"
              :key="food.name + index"
              class="food-card"
              @click="selectFood(food, index)"
              :class="{ 'selected': selectedFood === food }"
            >
              <div class="food-header">
                <h3>{{ food.name }}</h3>
                <span class="food-source">{{ food.source || '本地数据' }}</span>
              </div>
              <div class="food-info">
                <p><strong>区域：</strong>{{ food.campus_area }}</p>
                <p><strong>类型：</strong>{{ food.cuisine }}</p>
                <p><strong>价格：</strong>{{ food.avg_price ? `¥${food.avg_price}` : '暂无' }}</p>
                <p><strong>评分：</strong>{{ food.rating ? `${food.rating}分` : '暂无' }}</p>
                <p><strong>距离：</strong>{{ food.distance }}米</p>
                <p v-if="food.taste && food.taste.length"><strong>口味：</strong>{{ food.taste.join('、') }}</p>
                <p><strong>营业时间：</strong>{{ food.opening_hours }}</p>
                <p v-if="food.is_open !== null"><strong>状态：</strong>
                  <span :class="food.is_open ? 'status-open' : 'status-closed'">
                    {{ food.is_open ? '营业中' : '已打烊' }}
                  </span>
                </p>
                <p v-else><strong>状态：</strong><span class="status-unknown">营业状态未知</span></p>
              </div>
            </div>
          </div>
        </div>

        <!-- 地图容器 -->
        <div class="map-section">
          <h2>地图位置</h2>
          <div id="amap-container" class="amap-container"></div>
        </div>
      </main>
    </div>

    <!-- 详情抽屉 -->
    <div v-if="selectedFood" class="detail-drawer" @click.self="closeDetail">
      <div class="drawer-content">
        <button class="close-btn" @click="closeDetail">✕</button>
        <h2>{{ selectedFood.name }}</h2>
        <div class="detail-grid">
          <p><strong>区域：</strong>{{ selectedFood.campus_area }}</p>
          <p><strong>类型：</strong>{{ selectedFood.cuisine }}</p>
          <p><strong>价格：</strong>{{ selectedFood.avg_price ? `¥${selectedFood.avg_price}` : '暂无' }}</p>
          <p><strong>评分：</strong>{{ selectedFood.rating ? `${selectedFood.rating}分` : '暂无' }}</p>
          <p><strong>距离：</strong>{{ selectedFood.distance }}米</p>
          <p v-if="selectedFood.taste && selectedFood.taste.length"><strong>口味：</strong>{{ selectedFood.taste.join('、') }}</p>
          <p><strong>营业时间：</strong>{{ selectedFood.opening_hours }}</p>
          <p v-if="selectedFood.address"><strong>地址：</strong>{{ selectedFood.address }}</p>
          <p v-if="selectedFood.tel"><strong>电话：</strong>{{ selectedFood.tel }}</p>
          <p v-if="selectedFood.allergens && selectedFood.allergens.length"><strong>过敏原：</strong>{{ selectedFood.allergens.join('、') }}</p>
          <p v-if="selectedFood.meal_time && selectedFood.meal_time.length"><strong>适合：</strong>{{ selectedFood.meal_time.join('、') }}</p>
          <p><strong>坐标：</strong>{{ selectedFood.latitude }}, {{ selectedFood.longitude }}</p>
          <p><strong>数据来源：</strong>{{ selectedFood.source || '本地备用数据' }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'App',
  data() {
    return {
      filters: {
        campusArea: '',
        keywords: '',
        taste: [],
        maxPrice: null,
        maxDistance: null,
        minRating: null,
        mealTime: '',
        excludeAllergens: []
      },
      recommendations: [],
      filteredCount: 0,
      totalCandidates: 0,
      usingRealtime: false,
      loading: false,
      error: null,
      selectedFood: null,
      map: null,
      markers: [],
      infoWindow: null
    }
  },
  computed: {
    dataNotice() {
      return this.usingRealtime
        ? '当前显示高德地图实时POI数据'
        : '当前显示本地模拟数据（更新时间：2026-09-13）'
    }
  },
  mounted() {
    this.initMap()
    this.getRecommendations()
  },
  methods: {
    async getRecommendations() {
      this.loading = true
      this.error = null

      try {
        const params = new URLSearchParams()

        if (this.filters.campusArea) params.append('campus_area', this.filters.campusArea)
        if (this.filters.keywords) params.append('keywords', this.filters.keywords)
        if (this.filters.taste.length) params.append('taste', this.filters.taste.join(','))
        if (this.filters.maxPrice) params.append('max_price', this.filters.maxPrice)
        if (this.filters.maxDistance) params.append('max_distance', this.filters.maxDistance)
        if (this.filters.minRating) params.append('min_rating', this.filters.minRating)
        if (this.filters.mealTime) params.append('meal_time', this.filters.mealTime)
        if (this.filters.excludeAllergens.length) params.append('exclude_allergens', this.filters.excludeAllergens.join(','))

        const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
        const response = await fetch(`${apiBase}/api/recommend?${params}`)

        if (!response.ok) {
          throw new Error(`请求失败: ${response.status}`)
        }

        const data = await response.json()
        this.recommendations = data.results || []
        this.filteredCount = data.filtered_count || 0
        this.totalCandidates = data.total_candidates || 0
        this.usingRealtime = data.using_realtime || false

        // 更新地图标记
        this.updateMapMarkers()

      } catch (err) {
        this.error = `加载失败: ${err.message}。请检查后端服务是否启动。`
        console.error('获取推荐失败:', err)
      } finally {
        this.loading = false
      }
    },

    handleFilterChange() {
      // 自动触发搜索（可选，也可以只在点击按钮时触发）
      // this.getRecommendations()
    },

    resetFilters() {
      this.filters = {
        campusArea: '',
        keywords: '',
        taste: [],
        maxPrice: null,
        maxDistance: null,
        minRating: null,
        mealTime: '',
        excludeAllergens: []
      }
      this.getRecommendations()
    },

    selectFood(food, index) {
      this.selectedFood = food

      // 地图定位到选中的餐厅
      if (food.latitude && food.longitude && this.map) {
        this.map.setCenter([food.longitude, food.latitude])
        this.map.setZoom(16)

        // 显示信息窗
        const marker = this.markers.find(m => m.__foodId === (food.name + index))
        if (marker && this.infoWindow) {
          this.infoWindow.open(this.map, marker.getPosition())
        }
      }
    },

    closeDetail() {
      this.selectedFood = null
    },

    initMap() {
      if (typeof AMap === 'undefined') {
        console.error('❌ 高德地图未加载，地图功能不可用')
        return
      }

      console.log('✓ 开始初始化地图...')

      try {
        // 初始化地图（中心点设为清水河校区）
        this.map = new AMap.Map('amap-container', {
          zoom: 15,
          center: [103.9348, 30.7606],
          mapStyle: 'amap://styles/normal'
        })

        console.log('✓ 地图创建成功')

        // 高德地图2.0需要异步加载插件
        AMap.plugin(['AMap.Scale', 'AMap.ToolBar'], () => {
          // 添加控件
          this.map.addControl(new AMap.Scale())
          this.map.addControl(new AMap.ToolBar())
          console.log('✓ 地图控件添加成功')
        })

        // 初始化信息窗（信息窗不需要插件）
        this.infoWindow = new AMap.InfoWindow({
          offset: new AMap.Pixel(0, -30)
        })

        console.log('✓ 地图初始化完成')
      } catch (error) {
        console.error('❌ 地图初始化失败:', error)
      }
    },

    updateMapMarkers() {
      if (!this.map) return

      // 清除旧标记
      this.markers.forEach(marker => marker.setMap(null))
      this.markers = []

      // 添加新标记
      this.recommendations.forEach((food, index) => {
        if (!food.latitude || !food.longitude) return

        const marker = new AMap.Marker({
          position: [food.longitude, food.latitude],
          title: food.name,
          map: this.map
        })

        marker.__foodId = food.name + index
        marker.__foodData = food  // 保存完整的餐厅数据

        // 点击标记显示详情卡片（而不是信息窗）
        marker.on('click', () => {
          // 关闭信息窗
          this.infoWindow.close()

          // 显示详情卡片
          this.selectedFood = food

          // 地图居中到该位置
          this.map.setCenter([food.longitude, food.latitude])
          this.map.setZoom(16)
        })

        this.markers.push(marker)
      })

      // 自动调整视野
      if (this.markers.length > 0) {
        this.map.setFitView(this.markers)
      }
    }
  }
}
</script>

<style src="./style.css"></style>
