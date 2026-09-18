<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const runs = ref([])
const readings = ref([])
onMounted(async () => {
  const [h, r] = await Promise.all([getJSON('/api/history'), getJSON('/api/readings')])
  runs.value = h.items
  readings.value = r.items
})
const summary = (row) => {
  try { const r = JSON.parse(row.result_json); return r.total != null ? `¥${r.total}` : `平${r.plain_total}/尖${r.peak_total}` } catch { return '—' }
}
const KIND_TEXT = { estimate: '估计', confirmed: '正式', actual: '实抄' }
</script>
<template>
  <div class="page">
    <h1>测算记录</h1>
    <table>
      <thead><tr><th>#</th><th>类型</th><th>户号</th><th>结果摘要</th><th>时间</th></tr></thead>
      <tbody>
        <tr v-for="h in runs" :key="h.id">
          <td>{{ h.id }}</td><td>{{ h.kind }}</td><td>{{ h.account_id ?? '—' }}</td>
          <td>{{ summary(h) }}</td><td class="muted">{{ h.created_at }}</td>
        </tr>
      </tbody>
    </table>

    <h2 style="margin-top:1.6rem">抄表记录</h2>
    <table>
      <thead>
        <tr><th>#</th><th>户号</th><th>账期</th><th>类型</th><th>状态</th><th>电量</th><th>尖峰</th><th>结算为#</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in readings" :key="r.id">
          <td>{{ r.id }}</td>
          <td>{{ r.account_id }}</td>
          <td>{{ r.period || '—' }}</td>
          <td><span class="badge" :class="`badge-${r.kind}`">{{ KIND_TEXT[r.kind] || r.kind }}</span></td>
          <td>
            <span class="badge" :class="r.status === 'active' ? 'status-active' : 'status-closed'">
              {{ r.status === 'active' ? '有效' : '已关闭' }}
            </span>
          </td>
          <td>{{ r.kwh }}</td>
          <td>{{ r.peak ? '是' : '否' }}</td>
          <td v-if="r.settled_by_reading_id" class="muted">#{{ r.settled_by_reading_id }}</td>
          <td v-else>—</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
