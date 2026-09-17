<template><button class="food-card" :class="{ selected, 'food-card-pending': pending }" @click="$emit('select')">
  <div class="food-header"><h3>{{ food.name }}</h3><span class="food-source">{{ food.is_mock ? '示例' : sourceLabel(food) }}</span></div><p class="food-category">{{ food.campus_area || '区域未知' }}<span v-if="food.cuisine"> · {{ food.cuisine }}</span></p>
  <div class="food-metrics"><div><strong>{{ priceLabel(food.avg_price) }}</strong><span>人均参考价</span></div><div><strong>{{ food.rating != null ? food.rating : '—' }}<small v-if="food.rating != null"> 分</small></strong><span>参考评分</span></div></div>
  <div class="food-tags"><span v-for="taste in food.taste || []" :key="taste">{{ taste }}</span><span v-if="!food.taste?.length">口味未记录</span></div><div class="food-info"><p>参考距离 {{ food.distance != null ? `${food.distance} 米` : '未知' }}</p><p>{{ openingLabel(food) }}</p><p>参考时段：{{ food.opening_hours || '未知' }}</p></div>
  <p v-if="reason" class="food-reason">{{ reason }}</p><div v-if="pending" class="pending-reasons"><strong>待确认</strong><p v-for="item in food.unknown_constraints || []" :key="item">{{ unknownLabel(item) }}</p></div><span class="food-card-link">查看详情与数据来源 <span aria-hidden="true">↗</span></span>
</button></template>
<script setup>
import { sourceLabel, priceLabel, openingLabel } from './foodLabels.js'
defineProps({ food: Object, reason: String, selected: Boolean, pending: Boolean }); defineEmits(['select'])
function unknownLabel(key) { return ({ max_price: '人均参考价未知，预算条件待确认', avg_price: '人均参考价未知，预算条件待确认', price: '人均参考价未知，预算条件待确认', exclude_allergens: '过敏原信息不完整，忌口条件待确认', allergens: '过敏原信息不完整，忌口条件待确认', max_distance: '参考距离未知', distance: '参考距离未知', min_rating: '评分未知', rating: '评分未知', taste: '口味信息不足', exclude_taste: '需核实是否含排除的口味', meal_time: '用餐时段信息不足', exclude_cuisines: '餐饮类型信息不足', cuisine: '餐饮类型信息不足' })[key] || key }
</script>
