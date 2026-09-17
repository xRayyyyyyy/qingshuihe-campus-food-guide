<template><section class="active-filters" aria-label="当前已生效条件"><p><strong>当前条件</strong><span v-if="!chips.length">还没有限制，按评分推荐</span></p><div v-if="chips.length" class="filter-chips"><button v-for="chip in chips" :key="chip.key" :disabled="disabled" :aria-label="`移除${chip.label}条件`" @click="$emit('remove', chip.key)">{{ chip.label }} <span aria-hidden="true">×</span></button></div></section></template>
<script setup>
import { computed } from 'vue'
const props = defineProps({ constraints: Object, disabled: Boolean }); defineEmits(['remove'])
const chips = computed(() => {
  const c = props.constraints || {}, result = [], add = (key, label) => result.push({ key, label })
  if (c.campus_area) add('campus_area', c.campus_area)
  if (c.meal_time) add('meal_time', c.meal_time)
  if (c.keywords) add('keywords', `关键词：${c.keywords}`)
  if (c.max_price != null) add('max_price', `人均 ≤ ${c.max_price} 元`)
  if (c.max_distance != null) add('max_distance', `参考距离 ≤ ${c.max_distance} 米`)
  if (c.min_rating != null) add('min_rating', `评分 ≥ ${c.min_rating}`)
  if (c.taste?.length) add('taste', `口味：${c.taste.join('、')}`)
  if (c.exclude_taste?.length) add('exclude_taste', `避开口味：${c.exclude_taste.join('、')}`)
  if (c.exclude_cuisines?.length) add('exclude_cuisines', `排除类型：${c.exclude_cuisines.join('、')}`)
  if (c.exclude_allergens?.length) add('exclude_allergens', `忌口：${c.exclude_allergens.join('、')}`)
  if (c.exclude_ids?.length) add('exclude_ids', `已排除 ${c.exclude_ids.length} 家`)
  if (c.sort_by && c.sort_by !== 'rating') add('sort_by', c.sort_by === 'price' ? '参考价优先' : '参考距离优先')
  return result
})
</script>
