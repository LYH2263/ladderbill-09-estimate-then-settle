<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON, postJSON } from '../api'
import SegmentTable from '../components/SegmentTable.vue'

const route = useRoute()
const data = ref(null)
const bill = ref(null)
const peak = ref(false)

const STATUS = {
  estimated: { label: '估计有效', cls: 'badge-est' },
  confirmed: { label: '正式', cls: 'badge-ok' },
  settled: { label: '已结算', cls: 'badge-closed' },
}
const statusOf = (r) => STATUS[r.status] || { label: r.status, cls: 'badge-closed' }

const load = async () => {
  data.value = await getJSON(`/api/accounts/${route.params.id}`)
  const r = confirmedReading.value || data.value.readings[0]
  bill.value = r
    ? await postJSON('/api/bill', { account_id: +route.params.id, kwh: r.kwh, peak: !!r.peak, persist: false })
    : null
}
onMounted(load)
watch(() => route.params.id, load)

const account = computed(() => data.value?.account)
const readings = computed(() => data.value?.readings || [])
const settlements = computed(() => data.value?.settlements || [])
const confirmedReading = computed(() => readings.value.find((r) => r.status === 'confirmed'))
</script>

<template>
  <div class="page" v-if="account">
    <h1>{{ account.name }}</h1>
    <p class="muted">表号 {{ account.meter_no }} · {{ account.note }}</p>

    <div class="panel">
      <h3>最近抄表试算 <span class="muted">（只读）</span></h3>
      <label><input type="checkbox" v-model="peak" @change="bill = null" /> 尖峰</label>
      <button @click="load">刷新</button>
      <p v-if="bill">合计 <strong class="hero-num" style="font-size:1.5rem">¥{{ bill.total }}</strong></p>
      <SegmentTable :rows="bill?.segments || []" />
    </div>

    <div class="panel">
      <h3>抄表历史</h3>
      <table v-if="readings.length">
        <thead><tr><th>#</th><th>账期</th><th>电量(kWh)</th><th>尖峰</th><th>来源</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="r in readings" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.period || '—' }}</td>
            <td>{{ r.kwh }}</td>
            <td>{{ r.peak ? '是' : '否' }}</td>
            <td>{{ r.source === 'estimate' ? '估计' : '实际' }}</td>
            <td><span class="badge" :class="statusOf(r).cls">{{ statusOf(r).label }}</span></td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">暂无抄表</p>
    </div>

    <div class="panel">
      <h3>差值记录（估计结算）</h3>
      <table v-if="settlements.length">
        <thead>
          <tr><th>#</th><th>账期</th><th>估计电量</th><th>实际电量</th><th>差值电量</th><th>估计金额</th><th>实际金额</th><th>差值金额</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in settlements" :key="s.id">
            <td>{{ s.id }}</td>
            <td>{{ s.period }}</td>
            <td>{{ s.estimate_kwh }}</td>
            <td>{{ s.actual_kwh }}</td>
            <td :class="s.delta_kwh >= 0 ? 'delta-up' : 'delta-down'">
              {{ s.delta_kwh > 0 ? '+' : '' }}{{ s.delta_kwh }}
            </td>
            <td>¥{{ s.estimate_amount }}</td>
            <td>¥{{ s.actual_amount }}</td>
            <td :class="s.delta_amount >= 0 ? 'delta-up' : 'delta-down'">
              {{ s.delta_amount > 0 ? '+' : '' }}¥{{ s.delta_amount }}
            </td>
            <td class="muted">{{ s.created_at }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">暂无结算差值记录</p>
    </div>
  </div>
</template>

<style scoped>
.delta-up { color: #ff9d8a; font-weight: 600; }
.delta-down { color: var(--accent); font-weight: 600; }
</style>
