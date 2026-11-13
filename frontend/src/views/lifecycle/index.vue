<template>
  <section class="page" data-module="lifecycle">
    <header class="page-head">
      <div>
        <h2>表生命周期管理管理</h2>
        <p class="page-desc">维护数仓表的生命周期策略定义、归档路径与清理方式；到期清理演练以策略为主对象，联动数据保留规则与回收站给出唯一裁决。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出表生命周期管理清单</button>
      </div>
    </header>

    <div class="tabs">
      <button class="tab" :class="{ active: tab === 'policies' }" type="button" @click="tab = 'policies'">生命周期策略</button>
      <button class="tab" :class="{ active: tab === 'drill' }" type="button" @click="switchToDrill">到期清理演练</button>
    </div>

    <!-- ===================== 策略清单（原页面） ===================== -->
    <template v-if="tab === 'policies'">
      <div class="stat-row">
        <article v-for="item in stats" :key="item.label" class="stat-card">
          <span class="stat-label">{{ item.label }}</span>
          <strong class="stat-value">{{ item.value }}</strong>
        </article>
      </div>

      <form class="filter-bar" @submit.prevent="reload">
        <label v-for="field in filterFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input v-model="filters[field]" :placeholder="`按${field}检索`" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
            <td class="row-actions">
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 1" class="empty-state">暂无表生命周期管理数据，可先登记生命周期策略</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条表生命周期管理记录</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </template>

    <!-- ===================== 到期清理演练联动裁决视图 ===================== -->
    <template v-else>
      <p class="inline-note">
        演练只做模拟裁决，<strong>不会删除或修改任何业务记录</strong>；命中保留规则例外清单的表一律延期（合规依据优先），
        普通规则冲突时按更长保留期给出唯一优先结论，其余数据才允许进入清理演练。
      </p>

      <div class="version-bar">
        <span>视图生成：<strong>{{ candidateView?.生成时间 ?? '—' }}</strong></span>
        <span>保留规则版本：<strong>v{{ candidateView?.保留规则版本 ?? '—' }}</strong></span>
        <span>回收窗口版本：<strong>v{{ candidateView?.回收窗口版本 ?? '—' }}</strong></span>
        <span>当前操作人：<strong>{{ session.operator }}</strong></span>
        <button class="btn" type="button" @click="reloadDrillAll">刷新联动视图</button>
      </div>

      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">候选策略总数</span>
          <strong class="stat-value">{{ candidateView?.候选总数 ?? 0 }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">可清理（高风险）</span>
          <strong class="stat-value">{{ candidateView?.分类数量['可清理'] ?? 0 }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">延期（合规例外保护）</span>
          <strong class="stat-value">{{ candidateView?.分类数量['延期'] ?? 0 }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">受限（更长保留期）</span>
          <strong class="stat-value">{{ candidateView?.分类数量['受限'] ?? 0 }}</strong>
        </article>
      </div>

      <div v-if="drillMessage" :class="drillMessage.error ? 'error-text' : 'inline-note'">{{ drillMessage.text }}</div>

      <table class="data-table">
        <thead>
          <tr>
            <th>风险</th>
            <th>策略编号（主对象）</th>
            <th>表名称 / 数据集</th>
            <th>策略保留天数</th>
            <th>归档路径 / 清理方式</th>
            <th>裁决结果</th>
            <th>优先口径与依据</th>
            <th>保留规则意见</th>
            <th>回收站恢复窗口</th>
            <th>最近演练</th>
            <th>演练操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in candidateView?.候选策略 ?? []" :key="item.策略编号">
            <td><span class="badge" :class="riskClass(item.风险等级)">{{ item.风险等级 }} · {{ item.风险分 }}</span></td>
            <td>
              <strong>{{ item.策略编号 }}</strong>
              <div class="inline-note">{{ item.策略状态 }}</div>
            </td>
            <td>{{ item.表名称 }}<div class="inline-note">{{ item.数据集 }}</div></td>
            <td>{{ item.策略保留天数 }} 天</td>
            <td>{{ item.归档路径 }}<div class="inline-note">{{ item.清理方式 }}</div></td>
            <td><span class="badge" :class="verdictClass(item.裁决结果)">{{ item.裁决结果 }}</span></td>
            <td class="reason-cell">
              <strong>{{ item.优先口径 }}</strong>
              <div>{{ item.裁决依据 }}</div>
            </td>
            <td>
              <template v-if="item.命中保留规则">
                {{ item.命中保留规则 }}（{{ item.命中规则保留天数 }} 天）
                <div v-if="item.例外命中" class="badge badge-defer">例外命中</div>
                <div v-if="item.合规依据" class="inline-note">{{ item.合规依据 }}</div>
              </template>
              <span v-else class="inline-note">无规则覆盖</span>
            </td>
            <td>
              <template v-if="item.回收窗口">
                {{ item.回收窗口.回收记录编号 }}
                <div class="inline-note">
                  尚余 <strong>{{ item.回收窗口.剩余恢复天数 }}</strong> 天
                </div>
                <div class="inline-note">截止 {{ item.回收窗口.可恢复截止 }}（{{ item.回收窗口.窗口状态 }}）</div>
              </template>
              <span v-else class="inline-note">无在窗回收记录</span>
            </td>
            <td>
              <template v-if="item.最近演练批次号">
                <button class="link" type="button" @click="openBatch(item.最近演练批次号)">{{ item.最近演练批次号 }}</button>
                <div class="inline-note">{{ item.最近演练裁决 }}</div>
              </template>
              <span v-else class="inline-note">未演练</span>
            </td>
            <td>
              <button class="btn primary" type="button" :disabled="drillingId === item.生命周期策略ID"
                      @click="runDrill(item)">
                {{ drillingId === item.生命周期策略ID ? '裁决中…' : '发起演练' }}
              </button>
            </td>
          </tr>
          <tr v-if="!(candidateView?.候选策略.length)">
            <td colspan="11" class="empty-state">暂无候选生命周期策略</td>
          </tr>
        </tbody>
      </table>

      <div class="drill-grid" style="margin-top: 14px">
        <div class="panel">
          <div class="panel-head">数据保留规则（裁决输入 · v{{ candidateView?.保留规则版本 ?? '—' }}）</div>
          <div class="panel-body">
            <table class="data-table">
              <thead>
                <tr><th>规则编号</th><th>数据集范围</th><th>保留天数</th><th>例外清单</th><th>合规依据</th><th>状态</th></tr>
              </thead>
              <tbody>
                <tr v-for="rule in candidateView?.保留规则明细 ?? []" :key="String(rule.id)">
                  <td>{{ rule['规则编号'] }}</td>
                  <td>{{ rule['数据集范围'] }}</td>
                  <td>{{ rule['保留天数'] }}</td>
                  <td>{{ rule['例外清单'] || '—' }}</td>
                  <td>{{ rule['合规依据'] }}</td>
                  <td>{{ rule['规则状态'] || rule['status'] }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">回收记录与恢复窗口（裁决输入 · v{{ candidateView?.回收窗口版本 ?? '—' }}）</div>
          <div class="panel-body">
            <table class="data-table">
              <thead>
                <tr><th>记录编号</th><th>表名称</th><th>删除时间</th><th>可恢复期</th><th>窗口天数</th><th>状态</th></tr>
              </thead>
              <tbody>
                <tr v-for="record in candidateView?.回收记录明细 ?? []" :key="String(record.id)">
                  <td>{{ record['记录编号'] }}</td>
                  <td>{{ record['表名称'] }}</td>
                  <td>{{ record['删除时间'] }}</td>
                  <td>{{ record['可恢复期'] }}</td>
                  <td>{{ record['恢复窗口天数'] }}</td>
                  <td>{{ record['status'] }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          演练批次历史（旧结论按原口径留档，规则/窗口变化后新批次按新版本重算）
          <span class="inline-note">共 {{ batches.length }} 个批次</span>
        </div>
        <div class="panel-body">
          <table class="data-table">
            <thead>
              <tr><th>批次号</th><th>策略编号</th><th>发起人</th><th>发起时间</th><th>冻结版本快照</th><th>裁决</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="batch in batches" :key="batch.批次号">
                <td><button class="link" type="button" @click="openBatch(batch.批次号)">{{ batch.批次号 }}</button></td>
                <td>{{ batch.策略编号 }}</td>
                <td>{{ batch.发起人 }}</td>
                <td>{{ batch.发起时间 }}</td>
                <td class="reason-cell">
                  生命周期 v{{ batch.版本快照.生命周期版本 }} / 保留规则 v{{ batch.版本快照.保留规则版本 }}
                  / 回收窗口 v{{ batch.版本快照.回收窗口版本 }}
                </td>
                <td>
                  <span v-for="(verdict, code) in batch.裁决快照" :key="code" class="badge" :class="verdictClass(verdict)">
                    {{ code }}：{{ verdict }}
                  </span>
                </td>
                <td>{{ batch.状态 }}</td>
                <td><button class="btn" type="button" @click="openBatch(batch.批次号)">查看冻结结论</button></td>
              </tr>
              <tr v-if="!batches.length">
                <td colspan="8" class="empty-state">尚未发起任何演练批次</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="selectedBatch" class="panel">
        <div class="panel-head" @click="selectedBatch = null">
          批次 {{ selectedBatch.批次号 }} 冻结结论（点击收起）
        </div>
        <div class="panel-body">
          <div class="snapshot-box">
            输入指纹：{{ selectedBatch.输入指纹 }}<br />
            冻结版本：生命周期 v{{ selectedBatch.版本快照.生命周期版本 }} ·
            保留规则 v{{ selectedBatch.版本快照.保留规则版本 }} ·
            回收窗口 v{{ selectedBatch.版本快照.回收窗口版本 }}
          </div>
          <table class="data-table">
            <thead>
              <tr><th>策略编号</th><th>裁决</th><th>优先口径</th><th>裁决依据</th><th>命中规则</th><th>回收窗口剩余天数</th></tr>
            </thead>
            <tbody>
              <tr v-for="detail in selectedBatch.裁决明细" :key="detail.策略编号">
                <td>{{ detail.策略编号 }}</td>
                <td><span class="badge" :class="verdictClass(detail.裁决结果)">{{ detail.裁决结果 }}</span></td>
                <td>{{ detail.优先口径 }}</td>
                <td class="reason-cell">{{ detail.裁决依据 }}</td>
                <td>{{ detail.命中保留规则 ?? '—' }}</td>
                <td>{{ detail.回收窗口?.剩余恢复天数 ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import {
  getBatch,
  getCandidates,
  listBatches,
  startDrill,
  type Candidate,
  type CandidateView,
  type DrillBatch,
  type Verdict,
} from '@/api/drill'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null>

const session = useSessionStore()
const ENDPOINT = '/api/lifecycle'
const columns = ['策略编号', '表名称', '创建日期', '保留天数', '归档路径', '清理方式', '最后操作', '策略状态']
const actions = ['启用策略', '归档表', '删除表']
const stats = [{ label: '生命周期策略总数', value: 0 }, { label: '生效中策略', value: 0 }, { label: '已到期策略', value: 0 }]

const tab = ref<'policies' | 'drill'>('policies')
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// ---------------- 演练联动视图状态
const candidateView = ref<CandidateView | null>(null)
const batches = ref<DrillBatch[]>([])
const selectedBatch = ref<DrillBatch | null>(null)
const drillingId = ref<number | null>(null)
const drillMessage = ref<{ text: string; error: boolean } | null>(null)

function verdictClass(verdict: Verdict): string {
  if (verdict === '可清理') return 'badge-clean'
  if (verdict === '延期') return 'badge-defer'
  if (verdict === '受限') return 'badge-limited'
  return 'badge-muted'
}

function riskClass(level: string): string {
  if (level === '高') return 'badge-risk-high'
  if (level === '中') return 'badge-risk-middle'
  return 'badge-risk-low'
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('表生命周期管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '表生命周期管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('生命周期策略列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '表生命周期管理列表读取失败'
  }
}

async function reloadDrillAll() {
  try {
    const [view, batchList] = await Promise.all([getCandidates(), listBatches()])
    candidateView.value = view
    batches.value = batchList.items
  } catch (error) {
    drillMessage.value = {
      text: error instanceof Error ? error.message : '演练联动视图加载失败',
      error: true,
    }
  }
}

function switchToDrill() {
  tab.value = 'drill'
  drillMessage.value = null
  void reloadDrillAll()
}

async function runDrill(item: Candidate) {
  drillingId.value = item.生命周期策略ID
  drillMessage.value = null
  try {
    const result = await startDrill(item.生命周期策略ID, session.operator)
    drillMessage.value = {
      text: `${result.message}：批次 ${result.entry.批次号}，${item.策略编号} 裁决为「${result.entry.裁决快照[item.策略编号]}」`,
      error: false,
    }
    await reloadDrillAll()
    await openBatch(result.entry.批次号)
  } catch (error) {
    const status = (error as Error & { status?: number }).status
    drillMessage.value = {
      text: status === 409
        ? `并发冲突：${(error as Error).message}（后到请求已拒绝，结果回写审计清单）`
        : (error instanceof Error ? error.message : '演练发起失败'),
      error: true,
    }
    await reloadDrillAll()
  } finally {
    drillingId.value = null
  }
}

async function openBatch(batchNo: string | null) {
  if (!batchNo) return
  selectedBatch.value = await getBatch(batchNo)
}

onMounted(reload)
</script>
