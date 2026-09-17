<template>
  <section class="chat-panel panel" aria-labelledby="chat-title">
    <div class="section-heading chat-heading"><div><p class="eyebrow dark-eyebrow">把条件交给我</p><h2 id="chat-title">聊聊这顿吃什么</h2></div><button class="text-button" :disabled="busy || !hasSession" @click="$emit('new-session')">＋ 新对话</button></div>
    <div class="agent-status" :class="{ 'agent-online': agentStatus.configured }" role="status"><span class="status-dot"></span><span>{{ agentStatus.checking ? '正在检查对话服务…' : agentStatus.configured ? '模型配置已检测 · 本次会话会保留用餐条件' : agentStatus.message || '自然语言对话尚未启用' }}</span><button v-if="!agentStatus.configured" class="text-button" :disabled="agentStatus.checking || busy" @click="$emit('refresh-status')">重新检测</button></div>
    <p v-if="!agentStatus.configured && !agentStatus.checking" class="setup-note">自然语言对话需在后端 .env 配置模型服务。现在可以使用筛选条件获取推荐。</p>
    <div ref="messageList" class="chat-messages" role="log" aria-label="对话记录" aria-live="polite" aria-relevant="additions">
      <div v-if="!messages.length" class="chat-welcome"><span class="assistant-avatar" aria-hidden="true">✦</span><div><h3>想吃什么，直接说就好。</h3><p>可以告诉我区域、人均预算和口味；下一句只说要调整的条件。</p></div></div>
      <article v-for="message in messages" :key="message.id" class="chat-message" :class="`message-${message.role}`">
        <p class="message-author">{{ message.role === 'user' ? '你' : '觅食助手' }}<span v-if="message.status === 'degraded'" class="message-status">使用已核实的查询结果</span><span v-if="message.status === 'needs_clarification'" class="message-status">需要确认</span></p>
        <p class="message-text">{{ message.text }}</p><div v-if="message.foods?.length" class="chat-food-links"><button v-for="food in message.foods" :key="food.id" @click="$emit('select-food', food)">{{ food.name }} <span aria-hidden="true">↗</span></button></div>
        <details v-if="message.events?.length" class="tool-details"><summary>查看本次查询记录</summary><ul><li v-for="(event, index) in message.events" :key="index">{{ toolLabel(event.tool) }} · {{ eventLabel(event.status) }}</li></ul></details>
      </article>
      <div v-if="busy" class="chat-thinking" role="status"><span class="spinner"></span>正在整理推荐，请稍等…</div>
    </div>
    <div v-if="suggestions.length" class="suggestion-group"><p>你可以选择调整条件：</p><button v-for="suggestion in suggestions" :key="suggestion.id" :disabled="busy" @click="$emit('suggest', suggestion)">{{ suggestion.label }}<span v-if="suggestion.count != null"> · {{ suggestion.count }} 家</span></button></div>
    <div v-if="!messages.length" class="example-messages" aria-label="试试这些问题"><button v-for="example in examples" :key="example" :disabled="busy || !agentStatus.configured" @click="useExample(example)">{{ example }}</button></div>
    <form class="chat-composer" @submit.prevent="send"><label class="sr-only" for="chat-input">描述你的用餐需求</label><textarea id="chat-input" ref="input" v-model="draft" rows="2" maxlength="2000" :disabled="busy || !agentStatus.configured" :placeholder="agentStatus.configured ? '例如：晚饭在食堂吃，清淡点，人均 15 元以内' : '配置模型服务后，即可开始自然语言对话'" @keydown="handleKeydown"></textarea><div class="composer-footer"><span>Enter 发送 · Shift + Enter 换行</span><button class="btn-primary" type="submit" :disabled="busy || !agentStatus.configured || !draft.trim()">{{ busy ? '处理中…' : '发送 ↗' }}</button></div></form>
    <button v-if="retryAvailable" class="retry-button" :disabled="busy" @click="$emit('retry')">重试刚才的请求</button><p class="chat-footnote">推荐依据来自餐厅记录。缺失的价格、过敏原或营业信息会明确标注。</p>
  </section>
</template>
<script setup>
import { ref, watch, nextTick } from 'vue'
const props = defineProps({ messages: Array, busy: Boolean, agentStatus: Object, suggestions: Array, hasSession: Boolean, retryAvailable: Boolean })
const emit = defineEmits(['send', 'new-session', 'suggest', 'refresh-status', 'retry', 'select-food'])
const draft = ref(''), messageList = ref(null), input = ref(null)
const examples = ['晚饭在食堂吃，清淡点，人均 15 元以内', '南门有什么推荐？人均 30 元', '找评分高一点的面馆']
function send() { if (!draft.value.trim() || props.busy || !props.agentStatus.configured) return; emit('send', draft.value); draft.value = '' }
function useExample(example) { draft.value = example; input.value?.focus() }
function handleKeydown(event) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send() } }
function toolLabel(tool) { return ({ search_foods: '检索餐厅', get_food_details: '查看餐厅信息', compare_foods: '比较餐厅', suggest_constraint_changes: '核对可选调整', update_constraints: '更新用餐条件' })[tool] || '核对查询结果' }
function eventLabel(status) { return ({ ok: '完成', completed: '完成', empty: '暂无匹配结果', unavailable: '暂不可用', invalid_input: '条件需要调整', error: '未完成' })[status] || '已处理' }
watch(() => [props.messages.length, props.busy], async () => { await nextTick(); if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight })
watch(() => props.hasSession, value => { if (!value) draft.value = '' })
</script>
