<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON, postJSON } from '../api'
import SegmentTable from '../components/SegmentTable.vue'

const route = useRoute()
const data = ref(null)
const errorMsg = ref('')

// 录入表单
const period = ref(new Date().toISOString().slice(0, 7))
const kwh = ref(200)
const peak = ref(false)
const kind = ref('estimate')
const submitting = ref(false)

// 试算结果
const trial = ref(null)
// 结算目标与实抄录入
const settleTarget = ref(null)
const actualKwh = ref(0)
const actualPeak = ref(false)
const settling = ref(false)
const settleResult = ref(null)
// 正式测算结果
const formal = ref(null)

const KIND_TEXT = { estimate: '估计', confirmed: '正式', actual: '实抄' }

const account = computed(() => data.value?.account)
const readings = computed(() => data.value?.readings || [])
const settlements = computed(() => data.value?.settlements || [])

const load = async () => {
  errorMsg.value = ''
  data.value = await getJSON(`/api/accounts/${route.params.id}`)
  trial.value = null
  settleTarget.value = null
  settleResult.value = null
  formal.value = null
}
onMounted(load)
watch(() => route.params.id, load)

const showError = (e) => {
  errorMsg.value = e?.message || String(e)
}

const submitReading = async () => {
  errorMsg.value = ''
  submitting.value = true
  try {
    await postJSON('/api/readings', {
      account_id: +route.params.id,
      period: period.value,
      kind: kind.value,
      kwh: Number(kwh.value),
      peak: peak.value,
    })
    await load()
  } catch (e) {
    showError(e) // 409 等冲突：可读拒绝
  } finally {
    submitting.value = false
  }
}

// 试算：只读，不写运行记录
const runTrial = async (r) => {
  errorMsg.value = ''
  settleTarget.value = null
  settleResult.value = null
  formal.value = null
  try {
    trial.value = await getJSON(`/api/readings/${r.id}/trial`)
  } catch (e) {
    showError(e)
  }
}

const startSettle = (r) => {
  errorMsg.value = ''
  trial.value = null
  formal.value = null
  settleResult.value = null
  settleTarget.value = r
  actualKwh.value = r.kwh
  actualPeak.value = !!r.peak
}

const cancelSettle = () => {
  settleTarget.value = null
}

// 结算：录入实抄电量 → 关估计 + 差值记录（后端单事务）
const submitSettle = async () => {
  if (!settleTarget.value) return
  errorMsg.value = ''
  settling.value = true
  try {
    settleResult.value = await postJSON(
      `/api/readings/${settleTarget.value.id}/settle`,
      { actual_kwh: Number(actualKwh.value), peak: actualPeak.value },
    )
    settleTarget.value = null
    await load()
  } catch (e) {
    showError(e)
  } finally {
    settling.value = false
  }
}

// 结算成功后对实际电量正式测算（入库 calc_runs）
const runFormal = async (r) => {
  errorMsg.value = ''
  trial.value = null
  settleTarget.value = null
  try {
    formal.value = {
      reading_id: r.id,
      result: await postJSON('/api/bill', {
        account_id: +route.params.id,
        kwh: Number(r.kwh),
        peak: !!r.peak,
        persist: true,
      }),
    }
    await load()
  } catch (e) {
    showError(e)
  }
}
</script>

<template>
  <div class="page" v-if="account">
    <h1>{{ account.name }}</h1>
    <p class="muted">表号 {{ account.meter_no }} · {{ account.note }}</p>

    <p v-if="errorMsg" class="alert-error">⚠️ {{ errorMsg }}</p>

    <!-- 1. 录入估计/正式抄表 -->
    <div class="panel">
      <h3>本期抄表录入</h3>
      <div class="form-row">
        <label>账期 <input type="month" v-model="period" /></label>
        <label>
          类型
          <select v-model="kind">
            <option value="estimate">估计</option>
            <option value="confirmed">正式</option>
          </select>
        </label>
        <label>电量(kWh) <input type="number" v-model.number="kwh" min="0" step="1" /></label>
        <label><input type="checkbox" v-model="peak" /> 尖峰</label>
        <button :disabled="submitting" @click="submitReading">
          {{ kind === 'estimate' ? '写入估计抄表' : '写入正式抄表' }}
        </button>
      </div>
      <p class="muted hint">先写入估计抄表 → 试算查看分段 → 月底录入实抄完成结算。同户同账期只能有一条有效记录。</p>
    </div>

    <!-- 2. 估计试算分段 -->
    <div v-if="trial" class="panel">
      <h3>
        试算（只读）·
        记录 #{{ trial.reading.id }} ·
        <span class="badge" :class="`badge-${trial.reading.kind}`">{{ KIND_TEXT[trial.reading.kind] }}</span>
        · {{ trial.reading.kwh }} kWh
      </h3>
      <p>合计 <strong class="hero-num" style="font-size:1.5rem">¥{{ trial.calc.total }}</strong>
        <span class="muted">（试算不入运行记录，不改变状态）</span></p>
      <SegmentTable :rows="trial.calc.segments" />
    </div>

    <!-- 3. 结算：录入实抄 -->
    <div v-if="settleTarget" class="panel settle-box">
      <h3>结算估计记录 #{{ settleTarget.id }}（账期 {{ settleTarget.period }}）</h3>
      <div class="form-row">
        <label>实际电量(kWh) <input type="number" v-model.number="actualKwh" min="0" step="1" /></label>
        <label><input type="checkbox" v-model="actualPeak" /> 尖峰（默认沿用估计）</label>
        <button :disabled="settling" @click="submitSettle">确认结算</button>
        <button class="btn-ghost" @click="cancelSettle">取消</button>
      </div>
    </div>

    <!-- 结算结果 -->
    <div v-if="settleResult" class="panel">
      <h3>结算完成 · 差值记录 #{{ settleResult.settlement.id }}</h3>
      <p>
        估计 {{ settleResult.settlement.estimate_kwh }} kWh / ¥{{ settleResult.settlement.estimate_amount }}
        → 实抄 {{ settleResult.settlement.actual_kwh }} kWh / ¥{{ settleResult.settlement.actual_amount }}
      </p>
      <p>
        电量差 <strong :class="settleResult.settlement.delta_kwh >= 0 ? 'delta-pos' : 'delta-neg'">
          {{ settleResult.settlement.delta_kwh > 0 ? '+' : '' }}{{ settleResult.settlement.delta_kwh }} kWh
        </strong>
        · 金额差 <strong :class="settleResult.settlement.delta_amount >= 0 ? 'delta-pos' : 'delta-neg'">
          {{ settleResult.settlement.delta_amount > 0 ? '+' : '' }}¥{{ settleResult.settlement.delta_amount }}
        </strong>
      </p>
      <h4 class="muted">实抄正式分段</h4>
      <SegmentTable :rows="settleResult.actual_calc.segments" />
      <p class="muted">估计有效态已关闭；可对实抄电量发起正式测算入库。</p>
    </div>

    <!-- 正式测算结果 -->
    <div v-if="formal" class="panel">
      <h3>正式测算 · 记录 #{{ formal.reading_id }}</h3>
      <p>合计 <strong class="hero-num" style="font-size:1.5rem">¥{{ formal.result.total }}</strong>
        <span class="muted">已入运行记录 #{{ formal.result.run_id }}</span></p>
      <SegmentTable :rows="formal.result.segments" />
    </div>

    <!-- 历史：抄表记录（状态标记区分估计/正式） -->
    <div class="panel">
      <h3>抄表记录</h3>
      <table>
        <thead>
          <tr><th>#</th><th>账期</th><th>类型</th><th>状态</th><th>电量</th><th>尖峰</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in readings" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.period || '—' }}</td>
            <td><span class="badge" :class="`badge-${r.kind}`">{{ KIND_TEXT[r.kind] || r.kind }}</span></td>
            <td>
              <span class="badge" :class="r.status === 'active' ? 'status-active' : 'status-closed'">
                {{ r.status === 'active' ? '有效' : '已关闭' }}
              </span>
              <span v-if="r.settled_by_reading_id" class="muted"> → #{{ r.settled_by_reading_id }}</span>
            </td>
            <td>{{ r.kwh }}</td>
            <td>{{ r.peak ? '是' : '否' }}</td>
            <td class="actions">
              <button class="btn-sm" @click="runTrial(r)">试算</button>
              <button v-if="r.kind === 'estimate' && r.status === 'active'"
                      class="btn-sm btn-warn" @click="startSettle(r)">结算</button>
              <button v-if="r.status === 'active' && r.kind !== 'estimate'"
                      class="btn-sm" @click="runFormal(r)">正式测算</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 差值记录（户详情可查） -->
    <div class="panel">
      <h3>结算差值记录</h3>
      <table v-if="settlements.length">
        <thead>
          <tr>
            <th>#</th><th>账期</th><th>估计#</th><th>实抄#</th>
            <th>估计电量</th><th>实抄电量</th><th>电量差</th>
            <th>估计金额</th><th>实抄金额</th><th>金额差</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in settlements" :key="s.id">
            <td>{{ s.id }}</td>
            <td>{{ s.period }}</td>
            <td>#{{ s.estimate_reading_id }}</td>
            <td>#{{ s.actual_reading_id }}</td>
            <td>{{ s.estimate_kwh }}</td>
            <td>{{ s.actual_kwh }}</td>
            <td :class="s.delta_kwh >= 0 ? 'delta-pos' : 'delta-neg'">
              {{ s.delta_kwh > 0 ? '+' : '' }}{{ s.delta_kwh }}
            </td>
            <td>¥{{ s.estimate_amount }}</td>
            <td>¥{{ s.actual_amount }}</td>
            <td :class="s.delta_amount >= 0 ? 'delta-pos' : 'delta-neg'">
              {{ s.delta_amount > 0 ? '+' : '' }}¥{{ s.delta_amount }}
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">暂无结算差值记录</p>
    </div>
  </div>
</template>

<style scoped>
.form-row { display: flex; flex-wrap: wrap; gap: 1rem; align-items: end; }
input[type=number] { width: 7rem; }
input[type=month] { width: 9rem; }
.hint { margin-bottom: 0; font-size: 0.85rem; }
.alert-error {
  background: color-mix(in srgb, #e5484d 22%, transparent);
  border: 1px solid #e5484d;
  border-radius: 8px;
  padding: 0.55rem 0.8rem;
  color: #ffd7d9;
}
.settle-box { border: 1px solid var(--accent); }
.actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.btn-sm { padding: 0.2rem 0.55rem; font-size: 0.8rem; border-radius: 6px; }
.btn-ghost {
  background: transparent;
  color: var(--text);
  border: 1px solid var(--muted);
}
.btn-warn { background: #f0b429; }
.delta-pos { color: #ff9e9e; }
.delta-neg { color: #7ed4a0; }
</style>
