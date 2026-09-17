export const priceLabel = price => price == null ? '未知' : `¥${price}`
export const sourceLabel = food => food.is_mock ? '本地示例数据' : (food.source === 'amap' || food.source === '高德地图' ? '高德 POI' : food.source === 'local' ? '本地数据' : food.source || '来源未标明')
export const openingLabel = food => {
  if (food.is_mock || food.is_open == null || food.opening_status === 'unknown') return '营业状态未知'
  return food.is_open ? '来源标记为营业中，需核实' : '来源标记为未营业，需核实'
}
export const distanceLabel = basis => ({ unknown: '起点未记录，仅供参考', local_reference: '本地记录的参考距离，起点未记录', area_search_center: '相对区域查询中心的距离', search_center: '相对区域查询中心的距离', area_center: '相对区域查询中心的距离' })[basis] || basis || '起点未记录，仅供参考'
