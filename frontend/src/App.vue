<template>
  <div class="app-container">
    <header class="app-header"><div class="header-inner">
      <div class="brand-icon" aria-hidden="true">🍜</div>
      <div><p class="eyebrow">清水河 · 今天吃什么</p><h1>校园觅食 Agent</h1><p class="header-caption">说说你的口味和预算，一起找到这顿饭。</p></div>
      <span class="header-badge">{{ usingRealtime ? '高德 POI 数据' : '本地示例数据' }}</span>
    </div></header>

    <div class="main-content">
      <aside class="filter-panel panel" aria-labelledby="filters-title">
        <div class="section-heading"><h2 id="filters-title">筛选条件</h2><span class="small-label">也可以手动选</span></div>
        <form @submit.prevent="getRecommendations"><fieldset :disabled="busy">
          <div class="filter-group"><label for="campus-area">校区区域</label><select id="campus-area" v-model="filters.campus_area" @change="changeArea"><option :value="null">全部区域</option><option>学校食堂</option><option>南门</option><option>西门龙湖时代天街</option></select></div>
          <div class="filter-group"><label for="keywords">餐厅或类型关键词</label><input id="keywords" v-model="filters.keywords" maxlength="100" placeholder="例如：面、麻辣烫" @input="markChanged('keywords')"></div>
          <div class="filter-row">
            <div class="filter-group"><label for="meal-time">用餐时段</label><select id="meal-time" v-model="filters.meal_time" @change="markChanged('meal_time')"><option :value="null">不限</option><option>早餐</option><option>午餐</option><option>晚餐</option><option>夜宵</option></select></div>
            <div class="filter-group"><label for="max-price">人均预算 / 元</label><input id="max-price" v-model.number="filters.max_price" type="number" min="0" max="10000" step="1" placeholder="不限" @input="markChanged('max_price')"></div>
          </div>
          <fieldset class="filter-group choice-group"><legend>口味偏好</legend><div class="checkbox-group"><label v-for="taste in tasteOptions" :key="taste"><input v-model="filters.taste" type="checkbox" :value="taste" @change="markChanged('taste')">{{ taste }}</label></div></fieldset>
          <fieldset class="filter-group choice-group"><legend>不吃的口味</legend><div class="checkbox-group"><label v-for="taste in excludedTasteOptions" :key="taste"><input v-model="filters.exclude_taste" type="checkbox" :value="taste" @change="markChanged('exclude_taste')">{{ taste === '辣' ? '不吃辣' : taste }}</label></div></fieldset>
          <div class="filter-group"><label for="excluded-cuisines">排除餐饮类型</label><input id="excluded-cuisines" :value="filters.exclude_cuisines.join('、')" maxlength="100" placeholder="例如：火锅、烧烤" @change="editExcludedCuisines"><p class="field-hint">多个类型可用顿号或逗号分隔。</p></div>
          <div class="filter-group"><label for="max-distance">参考距离上限 / 米</label><input id="max-distance" v-model.number="filters.max_distance" type="number" min="0" max="100000" step="1" placeholder="不限" @input="markChanged('max_distance')"><p class="field-hint">数据中的参考距离，不代表从你的位置出发。</p></div>
          <div class="filter-row">
            <div class="filter-group"><label for="min-rating">最低评分</label><select id="min-rating" v-model.number="filters.min_rating" @change="markChanged('min_rating')"><option :value="null">不限</option><option v-for="rating in ratingOptions" :key="rating" :value="rating">{{ rating.toFixed(1) }} 分</option></select></div>
            <div class="filter-group"><label for="sort-by">优先排序</label><select id="sort-by" v-model="filters.sort_by" @change="markChanged('sort_by')"><option value="rating">评分更高</option><option value="price">参考价更低</option><option value="reference_distance">参考距离更近</option></select></div>
          </div>
          <fieldset class="filter-group choice-group"><legend>忌口 / 过敏原</legend><div class="checkbox-group"><label v-for="allergen in allergenOptions" :key="allergen"><input v-model="filters.exclude_allergens" type="checkbox" :value="allergen" @change="markChanged('exclude_allergens')">{{ allergen }}</label></div><p class="field-hint">缺少过敏原信息的餐厅会单独列为待确认，请向商家核实。</p></fieldset>
          <p v-if="dirtyFields.length" class="draft-notice">有待应用的更改，发送消息或获取推荐后生效。</p>
          <button class="btn-primary full-width" type="submit">{{ busy ? '正在查询…' : '获取推荐' }}</button>
          <button class="btn-secondary full-width" type="button" @click="resetFilters">清空条件并查询</button>
        </fieldset></form>
      </aside>

      <main class="results-section">
        <ChatPanel :messages="messages" :busy="busy" :agent-status="agentStatus" :suggestions="suggestions" :has-session="Boolean(sessionId || messages.length)" :retry-available="Boolean(failedRequest)" @send="sendMessage" @new-session="newConversation" @suggest="applySuggestion" @refresh-status="refreshAgentStatus" @retry="retryRequest" @select-food="selectFood" />
        <a class="mobile-filter-link" href="#filters-title">打开手动筛选 ↓</a>
        <ActiveFilters :constraints="activeConstraints" :disabled="busy" @remove="removeConstraint" />
        <div v-if="error" class="error-message" role="alert">{{ error }}</div>
        <section class="recommendation-section" aria-labelledby="results-title" :aria-busy="busy">
          <div class="results-header"><div><p class="eyebrow dark-eyebrow">为这一餐挑选</p><h2 id="results-title">推荐结果</h2></div><p class="result-stats">找到 {{ filteredCount }} 家<span v-if="recommendations.length"> · 展示 {{ recommendations.length }} 家</span></p></div>
          <div v-if="busy" class="progress-notice" role="status"><span class="spinner"></span>正在核对条件与餐厅信息…</div>
          <div v-if="recommendations.length" class="food-grid" :class="{ 'results-pending': busy }"><FoodCard v-for="food in recommendations" :key="food.id" :food="food" :reason="reasonFor(food.id)" :selected="selectedFood?.id === food.id" @select="selectFood(food)" /></div>
          <div v-else-if="!busy" class="no-results panel"><span aria-hidden="true">🥢</span><h3>当前数据中没有符合条件的餐厅</h3><p>可以调整预算、区域或口味，再试一次。忌口不会被自动放宽。</p></div>
          <div v-if="unknowns.length" class="data-note"><strong>还需要确认</strong><ul><li v-for="note in unknowns" :key="note">{{ note }}</li></ul></div>
        </section>
        <section v-if="pendingResults.length" class="pending-section" aria-labelledby="pending-title"><div class="section-heading"><h2 id="pending-title">待确认的候选</h2><span class="pending-badge">{{ pendingResults.length }} 家</span></div><p class="section-description">这些餐厅有信息缺失，尚不能确认满足全部条件。请先核实卡片中标明的信息。</p><div class="food-grid"><FoodCard v-for="food in pendingResults" :key="food.id" :food="food" pending @select="selectFood(food)" /></div></section>
        <section class="map-section panel" aria-labelledby="map-title"><div class="section-heading"><h2 id="map-title">在地图上看看</h2><span class="small-label">推荐餐厅的位置</span></div><div v-show="mapReady" id="amap-container" class="amap-container"></div><div v-if="!mapReady" class="map-placeholder"><span aria-hidden="true">⌖</span><strong>{{ mapMessage }}</strong><p>餐厅地址和参考位置可在详情中查看。</p></div></section>
        <p class="data-notice">{{ dataNotice }} 人均价格、距离与营业时段仅供参考；出发前请向商家确认。</p>
      </main>
    </div>

    <div v-if="selectedFood" class="detail-drawer" @click.self="closeDetail" @keydown.esc="closeDetail" @keydown.tab="trapDrawerFocus">
      <section ref="drawer" class="drawer-content" role="dialog" aria-modal="true" aria-labelledby="detail-title" tabindex="-1">
        <button class="close-btn" aria-label="关闭餐厅详情" @click="closeDetail">✕</button><p class="eyebrow dark-eyebrow">餐厅详情</p><h2 id="detail-title">{{ selectedFood.name }}</h2><p class="detail-source">{{ sourceLabel(selectedFood) }}</p>
        <dl class="detail-grid">
          <div><dt>区域</dt><dd>{{ selectedFood.campus_area || '未知' }}</dd></div><div><dt>类型</dt><dd>{{ selectedFood.cuisine || '未知' }}</dd></div>
          <div><dt>人均参考价</dt><dd>{{ priceLabel(selectedFood.avg_price) }}</dd></div><div><dt>参考评分</dt><dd>{{ selectedFood.rating != null ? `${selectedFood.rating} 分` : '未知' }}</dd></div>
          <div><dt>参考距离</dt><dd>{{ selectedFood.distance != null ? `${selectedFood.distance} 米` : '未知' }}</dd></div><div><dt>距离依据</dt><dd>{{ distanceLabel(selectedFood.distance_basis) }}</dd></div>
          <div><dt>口味标签</dt><dd>{{ selectedFood.taste?.join('、') || '未记录' }}</dd></div><div><dt>参考营业时段</dt><dd>{{ selectedFood.opening_hours || '未知' }}</dd></div><div><dt>营业状态</dt><dd>{{ openingLabel(selectedFood) }}</dd></div>
          <div><dt>地址</dt><dd>{{ selectedFood.address || '未记录' }}</dd></div><div v-if="selectedFood.tel"><dt>电话</dt><dd>{{ selectedFood.tel }}</dd></div>
          <div><dt>过敏原记录</dt><dd>{{ selectedFood.allergens?.length ? selectedFood.allergens.join('、') : '未采集 / 未知' }}<small>记录不代表完整配料清单，也不构成过敏安全保证，请向商家核实。</small></dd></div>
          <div v-if="selectedFood.meal_time?.length"><dt>适合时段</dt><dd>{{ selectedFood.meal_time.join('、') }}</dd></div><div v-if="selectedFood.data_updated_at"><dt>数据更新时间</dt><dd>{{ selectedFood.data_updated_at }}</dd></div>
        </dl>
        <button class="btn-secondary full-width" :disabled="busy || activeConstraints.exclude_ids.includes(selectedFood.id)" @click="excludeSelectedFood">这次不推荐这家</button>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import ChatPanel from './components/ChatPanel.vue'
import ActiveFilters from './components/ActiveFilters.vue'
import FoodCard from './components/FoodCard.vue'
import { sourceLabel, priceLabel, openingLabel, distanceLabel } from './components/foodLabels.js'

const defaults = () => ({ campus_area: null, keywords: null, meal_time: null, taste: [], max_price: null, max_distance: null, min_rating: null, exclude_allergens: [], exclude_taste: [], exclude_cuisines: [], exclude_ids: [], sort_by: 'rating', limit: 10 })
const filters = ref(defaults()), activeConstraints = ref(defaults()), dirtyFields = ref([])
const tasteOptions = computed(() => [...new Set(['清淡', '家常', '微辣', '麻辣', '重口味', '甜', ...filters.value.taste])])
const excludedTasteOptions = computed(() => [...new Set(['辣', ...filters.value.exclude_taste])])
const ratingOptions = computed(() => [...new Set([3, 4, 4.5, filters.value.min_rating].filter(value => typeof value === 'number'))].sort((a, b) => a - b))
const allergenOptions = computed(() => [...new Set(['花椒', '小麦', '奶制品', ...filters.value.exclude_allergens])])
const recommendations = ref([]), pendingResults = ref([]), reasons = ref([]), unknowns = ref([]), suggestions = ref([])
const filteredCount = ref(0), usingRealtime = ref(false), busy = ref(false), error = ref(''), messages = ref([])
const sessionId = ref(null), stateVersion = ref(null), failedRequest = ref(null)
const agentStatus = ref({ configured: false, mode: 'unavailable', message: '正在检查对话服务…', checking: true })
const selectedFood = ref(null), drawer = ref(null), mapReady = ref(false), mapMessage = ref('地图未启用')
const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
let generation = 0, map = null, markers = [], activeController = null, previousFocus = null, disposed = false
const dataNotice = computed(() => usingRealtime.value ? '当前包含高德 POI 查询数据，查询时间不代表商家信息更新时间。' : '当前使用本地示例数据，非实时商家信息。')
const reasonFor = id => reasons.value.filter(item => item.food_id === id).map(item => item.text).join('；')
const markChanged = key => { if (!dirtyFields.value.includes(key)) dirtyFields.value.push(key) }
function changeArea() {
  markChanged('campus_area')
  clearResults()
  getRecommendations()
}
const normalize = value => value === '' || value === undefined ? null : value
const changedValues = (all = false) => Object.fromEntries((all ? Object.keys(defaults()) : dirtyFields.value).map(key => [key, normalize(filters.value[key])]))
const clone = value => JSON.parse(JSON.stringify(value))

async function refreshAgentStatus() {
  agentStatus.value.checking = true
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 10000)
  try {
    const response = await fetch(`${apiBase}/api/agent/status`, { signal: controller.signal })
    if (!response.ok) throw new Error('服务暂不可用')
    agentStatus.value = { ...await response.json(), checking: false }
  } catch { agentStatus.value = { configured: false, mode: 'unavailable', checking: false, message: '暂时无法连接对话服务，请检查后端是否已启动。' } }
  finally { clearTimeout(timeout) }
}
function clearResults() { recommendations.value = []; pendingResults.value = []; reasons.value = []; unknowns.value = []; suggestions.value = []; filteredCount.value = 0; selectedFood.value = null; updateMapMarkers() }
function newConversation() {
  if (busy.value) return
  generation += 1; sessionId.value = null; stateVersion.value = null; messages.value = []
  filters.value = defaults(); activeConstraints.value = defaults(); dirtyFields.value = []
  failedRequest.value = null; error.value = ''; clearResults(); loadInitialRecommendations()
}
function getRecommendations() { submitTurn('', changedValues(true), '按当前筛选条件获取推荐') }
function resetFilters() { filters.value = defaults(); getRecommendations() }
function sendMessage(message) { if (agentStatus.value.configured && message.trim()) submitTurn(message.trim(), changedValues(), message.trim()) }
function applySuggestion(suggestion) { submitTurn('', suggestion.changes, `应用调整：${suggestion.label}`) }
function removeConstraint(key) { submitTurn('', { [key]: defaults()[key] }, '移除一项筛选条件') }
function editExcludedCuisines(event) { filters.value.exclude_cuisines = event.target.value.split(/[、,，]/).map(value => value.trim()).filter(Boolean); markChanged('exclude_cuisines') }
function excludeSelectedFood() {
  const food = selectedFood.value
  if (!food || busy.value) return
  closeDetail()
  submitTurn('', { exclude_ids: [...new Set([...activeConstraints.value.exclude_ids, food.id])] }, `这次不推荐：${food.name}`)
}
async function submitTurn(message, changes, displayMessage) {
  if (busy.value) return
  const body = { message, request_id: crypto.randomUUID() }
  if (sessionId.value) { body.session_id = sessionId.value; body.expected_state_version = stateVersion.value }
  if (Object.keys(changes).length) body.ui_changes = clone(changes)
  messages.value.push({ id: body.request_id, role: 'user', text: displayMessage })
  await performRequest(body)
}
async function retryRequest() { if (failedRequest.value && !busy.value) await performRequest(failedRequest.value) }
async function performRequest(body) {
  busy.value = true; error.value = ''; failedRequest.value = null
  const thisGeneration = ++generation, controller = new AbortController()
  activeController = controller
  const timeout = setTimeout(() => controller.abort(), 35000)
  try {
    const response = await fetch(`${apiBase}/api/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: controller.signal })
    const data = await response.json()
    if (thisGeneration !== generation || disposed) return
    if (response.status === 409) {
      const detail = data.detail || data
      if (!['session_expired', 'state_conflict'].includes(detail.code)) { error.value = detail.message || '暂时无法提交，请稍后重试。'; return }
      if (detail.code === 'session_expired') { sessionId.value = null; stateVersion.value = null; dirtyFields.value = Object.keys(defaults()) }
      else if (detail.constraints) { filters.value = { ...defaults(), ...detail.constraints }; activeConstraints.value = clone(filters.value); stateVersion.value = detail.state_version; dirtyFields.value = [] }
      clearResults()
      error.value = detail.code === 'session_expired' ? '对话已过期，筛选条件仍保留。请重新发送消息或获取推荐。' : '会话条件已更新，页面已同步。请检查条件后重新提交。'
      return
    }
    if (!response.ok) {
      const detail = data.detail, message = typeof detail === 'string' ? detail : detail?.message
      error.value = message || (response.status === 422 ? '条件格式有误，请检查输入范围后重试。' : `请求失败（${response.status}），请稍后重试。`)
      if (response.status >= 500) failedRequest.value = body
      return
    }
    sessionId.value = data.session_id; stateVersion.value = data.state_version
    filters.value = { ...defaults(), ...data.constraints }; activeConstraints.value = clone(filters.value); dirtyFields.value = []
    recommendations.value = data.foods || []; pendingResults.value = data.pending_results || []; reasons.value = data.reasons || []; unknowns.value = data.unknowns || []; suggestions.value = data.suggested_changes || []
    filteredCount.value = data.filtered_count ?? recommendations.value.length; usingRealtime.value = Boolean(data.using_realtime); selectedFood.value = null
    messages.value.push({ id: `${body.request_id}-reply`, role: 'assistant', text: data.reply || data.clarification || '查询完成。', status: data.status, foods: [...recommendations.value], events: data.tool_events || [] })
    if (messages.value.length > 40) messages.value = messages.value.slice(-40)
    await nextTick(); updateMapMarkers()
  } catch (err) {
    if (thisGeneration !== generation || disposed) return
    failedRequest.value = body
    error.value = err.name === 'AbortError' ? '等待超时。可以重试本次请求，已提交的条件不会重复应用。' : '连接失败，请检查后端服务后重试本次请求。'
  } finally { clearTimeout(timeout); if (thisGeneration === generation) { busy.value = false; activeController = null } }
}
async function loadInitialRecommendations() {
  busy.value = true
  const thisGeneration = ++generation, controller = new AbortController()
  activeController = controller
  const timeout = setTimeout(() => controller.abort(), 15000)
  try {
    const response = await fetch(`${apiBase}/api/chat`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: '', request_id: crypto.randomUUID(), ui_changes: defaults() }),
      signal: controller.signal,
    })
    if (!response.ok) throw new Error('无法读取推荐')
    const data = await response.json()
    if (thisGeneration !== generation || disposed) return
    sessionId.value = data.session_id; stateVersion.value = data.state_version
    activeConstraints.value = { ...defaults(), ...data.constraints }
    recommendations.value = data.results || data.foods || []; pendingResults.value = data.pending_results || []
    filteredCount.value = data.filtered_count ?? recommendations.value.length; usingRealtime.value = Boolean(data.using_realtime); unknowns.value = data.unknowns || []
    await nextTick(); updateMapMarkers()
  } catch { if (thisGeneration === generation && !disposed) error.value = '无法加载餐厅，请确认后端服务已启动，然后点击“获取推荐”。' }
  finally { clearTimeout(timeout); if (thisGeneration === generation) { busy.value = false; activeController = null } }
}
async function selectFood(food) { previousFocus = document.activeElement; selectedFood.value = food; if (map && food.latitude && food.longitude) map.setZoomAndCenter(16, [food.longitude, food.latitude]); await nextTick(); drawer.value?.focus() }
function closeDetail() { selectedFood.value = null; previousFocus?.focus() }
function trapDrawerFocus(event) {
  const focusable = drawer.value?.querySelectorAll('button, a, input, select, textarea, [tabindex="0"]')
  if (!focusable?.length) { event.preventDefault(); return }
  const first = focusable[0], last = focusable[focusable.length - 1]
  if (event.shiftKey && (document.activeElement === first || document.activeElement === drawer.value)) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
async function initMap() {
  const key = (import.meta.env.VITE_AMAP_JS_KEY || '').trim()
  if (!key || /your_|YOUR_|placeholder/i.test(key)) return
  mapMessage.value = '正在加载地图…'
  try {
    if (!window.AMap) {
      const securityCode = import.meta.env.VITE_AMAP_SECURITY_CODE
      if (securityCode) window._AMapSecurityConfig = { securityJsCode: securityCode }
      await new Promise((resolve, reject) => {
        const script = document.createElement('script'), timeout = setTimeout(() => reject(new Error('地图加载超时')), 12000)
        script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}`; script.async = true
        script.onload = () => { clearTimeout(timeout); resolve() }; script.onerror = () => { clearTimeout(timeout); reject(new Error('地图加载失败')) }
        document.head.appendChild(script)
      })
    }
    if (disposed) return
    mapReady.value = true; await nextTick()
    map = new window.AMap.Map('amap-container', { zoom: 15, center: [103.9348, 30.7606], mapStyle: 'amap://styles/normal' })
    window.AMap.plugin(['AMap.Scale', 'AMap.ToolBar'], () => { if (map) { map.addControl(new window.AMap.Scale()); map.addControl(new window.AMap.ToolBar()) } })
    updateMapMarkers()
  } catch { mapReady.value = false; mapMessage.value = '地图暂时无法加载' }
}
function updateMapMarkers() {
  if (!map) return
  markers.forEach(marker => marker.setMap(null)); markers = []
  recommendations.value.forEach(food => { if (!food.latitude || !food.longitude) return; const marker = new window.AMap.Marker({ position: [food.longitude, food.latitude], title: food.name, map }); marker.on('click', () => selectFood(food)); markers.push(marker) })
  if (markers.length) map.setFitView(markers)
}
onMounted(async () => { await nextTick(); await Promise.allSettled([refreshAgentStatus(), loadInitialRecommendations(), initMap()]) })
onBeforeUnmount(() => { disposed = true; generation += 1; activeController?.abort(); map?.destroy(); map = null })
</script>
<style src="./style.css"></style>
