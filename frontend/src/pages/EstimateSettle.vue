<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { getJSON, postJSON } from '../api'
import TierLadder from '../components/TierLadder.vue'
import SegmentTable from '../components/SegmentTable.vue'

const accounts = ref([])
const accountId = ref(null)
const period = ref(new Date().toISOString().slice(0, 7))

const readings = ref([])
const settlements = ref([])
const estKwh = ref(150)
const estPeak = ref(false)
const preview = ref(null)
const actualKwh = ref(null)
const actualPeak = ref(false)
const settlement = ref(null)
const formal = ref(null)
const error = ref('')
const busy = ref(false)

const estimate = computed(() =>
  readings.value.find((r) => r.period === period.value && r.status === 'estimated') || null
)
const confirmed = computed(() =>
  readings.value.find((r) => r.period === period.value && r.status === 'confirmed') || null
)
const periodSettlements = computed(() => settlements.value.filter((s) => s.period === period.value))

onMounted(async () => {
  accounts.value = (await getJSON('/api/accounts')).items
  if (accounts.value.length) accountId.value = accounts.value[0].id
})

watch([accountId, period], refresh)

async function refresh() {
  error.value = ''
  preview.value = null
  settlement.value = null
  formal.value = null
  if (!accountId.value || !period.value) return
  const d = await getJSON(`/api/accounts/${accountId.value}`)
  readings.value = d.readings
  settlements.value = d.settlements
  if (estimate.value) actualPeak.value = !!estimate.value.peak
}

async function guard(fn) {
  error.value = ''
  busy.value = true
  try {
    await fn()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

const saveEstimate = () =>
  guard(async () => {
    await postJSON('/api/readings', {
      account_id: accountId.value,
      period: period.value,
      kwh: estKwh.value,
      peak: estPeak.value,
      source: 'estimate',
    })
    await refresh()
  })

const runPreview = () =>
  guard(async () => {
    preview.value = await postJSON(`/api/readings/${estimate.value.id}/preview`, {})
  })

const settle = () =>
  guard(async () => {
    const out = await postJSON(`/api/readings/${estimate.value.id}/settle`, {
      actual_kwh: actualKwh.value,
      peak: actualPeak.value,
    })
    await refresh()
    settlement.value = out.settlement
  })

const runFormal = () =>
  guard(async () => {
    formal.value = await postJSON('/api/bill', {
      account_id: accountId.value,
      kwh: settlement.value.actual_kwh,
      peak: actualPeak.value,
      persist: true,
    })
  })
</script>

<template>
  <div class="page">
    <h1>估计抄表与结算</h1>

    <div class="panel form-row">
      <label>户号
        <select v-model.number="accountId">
          <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.name }}（{{ a.meter_no }}）</option>
        </select>
      </label>
      <label>账期 <input type="month" v-model="period" /></label>
    </div>

    <p v-if="error" class="panel error">⚠ {{ error }}</p>

    <!-- 1. 录入估计 -->
    <div v-if="!estimate && !confirmed && !settlement" class="panel">
      <h3>1 · 录入估计抄表</h3>
      <div class="form-row">
        <label>估计电量(kWh) <input type="number" v-model.number="estKwh" min="0" step="1" /></label>
        <label><input type="checkbox" v-model="estPeak" /> 尖峰</label>
        <button :disabled="busy" @click="saveEstimate">保存估计</button>
      </div>
    </div>

    <!-- 2. 估计试算（只读） -->
    <div v-if="estimate" class="panel">
      <h3>2 · 估计试算 <span class="badge badge-est">估计有效</span></h3>
      <p>估计电量 <strong>{{ estimate.kwh }} kWh</strong>
        <span v-if="estimate.peak" class="badge badge-peak">尖峰</span>
        <span class="muted">（试算只读，不写测算记录）</span>
      </p>
      <button :disabled="busy" @click="runPreview">试算分段</button>
      <template v-if="preview">
        <p>试算合计 <strong class="hero-num" style="font-size:1.5rem">¥{{ preview.total }}</strong></p>
        <TierLadder :segments="preview.segments" />
        <SegmentTable :rows="preview.segments" />
      </template>
    </div>

    <!-- 3. 录入实际并结算 -->
    <div v-if="estimate" class="panel">
      <h3>3 · 录入实际，完成结算</h3>
      <div class="form-row">
        <label>实际电量(kWh) <input type="number" v-model.number="actualKwh" min="0" step="1" /></label>
        <label><input type="checkbox" v-model="actualPeak" /> 尖峰</label>
        <button :disabled="busy || actualKwh === null || actualKwh === ''" @click="settle">结算</button>
      </div>
    </div>

    <!-- 4. 差值记录 + 正式测算 -->
    <div v-if="settlement" class="panel">
      <h3>4 · 结算完成 <span class="badge badge-ok">差值记录 #{{ settlement.id }}</span></h3>
      <table>
        <thead><tr><th>账期</th><th>估计电量</th><th>实际电量</th><th>差值电量</th><th>估计金额</th><th>实际金额</th><th>差值金额</th></tr></thead>
        <tbody>
          <tr>
            <td>{{ settlement.period }}</td>
            <td>{{ settlement.estimate_kwh }}</td>
            <td>{{ settlement.actual_kwh }}</td>
            <td :class="settlement.delta_kwh >= 0 ? 'delta-up' : 'delta-down'">
              {{ settlement.delta_kwh > 0 ? '+' : '' }}{{ settlement.delta_kwh }}
            </td>
            <td>¥{{ settlement.estimate_amount }}</td>
            <td>¥{{ settlement.actual_amount }}</td>
            <td :class="settlement.delta_amount >= 0 ? 'delta-up' : 'delta-down'">
              {{ settlement.delta_amount > 0 ? '+' : '' }}¥{{ settlement.delta_amount }}
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!formal"><button :disabled="busy" @click="runFormal">对实际电量正式测算（入库）</button></p>
      <template v-else>
        <p>正式测算合计 <strong class="hero-num" style="font-size:1.5rem">¥{{ formal.total }}</strong>
          <span class="muted">记录#{{ formal.run_id }}</span></p>
        <SegmentTable :rows="formal.segments" />
      </template>
    </div>

    <!-- 该账期已是正式抄表 -->
    <div v-if="confirmed && !settlement" class="panel">
      <h3>本账期已正式抄表 <span class="badge badge-ok">正式</span></h3>
      <p>{{ confirmed.kwh }} kWh <span class="muted">（#{{ confirmed.id }}，如需改期请切换账期）</span></p>
    </div>

    <!-- 本账期历史差值记录 -->
    <div v-if="periodSettlements.length" class="panel">
      <h3>本账期差值记录</h3>
      <table>
        <thead><tr><th>#</th><th>估计</th><th>实际</th><th>差值</th><th>金额差</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="s in periodSettlements" :key="s.id">
            <td>{{ s.id }}</td><td>{{ s.estimate_kwh }}</td><td>{{ s.actual_kwh }}</td>
            <td>{{ s.delta_kwh > 0 ? '+' : '' }}{{ s.delta_kwh }}</td>
            <td>{{ s.delta_amount > 0 ? '+' : '' }}¥{{ s.delta_amount }}</td>
            <td class="muted">{{ s.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.form-row { display: flex; flex-wrap: wrap; gap: 1rem; align-items: end; }
input[type=number] { width: 7rem; margin-left: 0.35rem; }
select, input[type=month] { margin-left: 0.35rem; background: #0d1612; border: 1px solid var(--muted); color: var(--text); padding: 0.35rem 0.5rem; border-radius: 6px; }
.error { color: #ff9d8a; border-left: 3px solid #ff9d8a; }
.delta-up { color: #ff9d8a; font-weight: 600; }
.delta-down { color: var(--accent); font-weight: 600; }
h3 { margin-top: 0; }
</style>
