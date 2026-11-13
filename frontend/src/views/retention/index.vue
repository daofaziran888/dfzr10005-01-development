<template>
  <section class="page" data-module="retention">
    <header class="page-head">
      <div>
        <h2>数据保留策略管理</h2>
        <p class="page-desc">维护数据保留的期限设定、过期动作与合规依据；联动到期清理演练，显示哪些数据集被演练占用以及规则给出的意见。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记保留规则</button>
        <button class="btn" type="button" @click="exportRows">导出数据保留策略清单</button>
      </div>
    </header>

    <div class="version-bar">
      <span>演练联动版本：<strong>保留规则 v{{ drillView?.保留规则版本 ?? '—' }}</strong></span>
      <span>被演练占用数据集：<strong>{{ drillView?.被占用数据集数 ?? 0 }}</strong> 个</span>
      <button class="btn" type="button" @click="reload">刷新演练联动</button>
    </div>

    <div class="panel">
      <div class="panel-head">本次演练占用的数据集（数据保留侧视角）</div>
      <div class="panel-body">
        <table class="data-table">
          <thead>
            <tr><th>数据集</th><th>占用批次</th><th>涉及生命周期策略</th><th>演练裁决</th><th>命中保留规则</th><th>冻结版本快照</th><th>占用状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in drillView?.items ?? []" :key="item.数据集">
              <td><strong>{{ item.数据集 }}</strong></td>
              <td>
                <span v-for="batchNo in item.占用批次" :key="batchNo" class="badge badge-muted" style="margin-right: 4px">
                  {{ batchNo }}
                </span>
              </td>
              <td>{{ item.涉及策略.join('、') }}</td>
              <td>
                <span v-for="verdict in item.裁决结果" :key="verdict" class="badge" :class="verdictClass(verdict)"
                      style="margin-right: 4px">
                  {{ verdict }}
                </span>
              </td>
              <td>{{ item.命中保留规则.join('、') || '—' }}</td>
              <td class="reason-cell">
                生命周期 v{{ item.冻结版本快照.生命周期版本 }} · 保留规则 v{{ item.冻结版本快照.保留规则版本 }}
                · 回收窗口 v{{ item.冻结版本快照.回收窗口版本 }}
              </td>
              <td>{{ item.占用状态 }}</td>
            </tr>
            <tr v-if="!(drillView?.items.length)">
              <td colspan="7" class="empty-state">暂无数据集被演练占用，可先到表生命周期页面发起到期清理演练</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

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
          <th>演练占用情况</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <template v-if="ruleOccupy(row)?.是否被演练占用">
              <span class="badge badge-limited">已占用</span>
              <div class="inline-note">数据集：{{ ruleOccupy(row)?.被占用数据集.join('、') }}</div>
            </template>
            <span v-else class="inline-note">未被演练占用</span>
          </td>
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
          <td :colspan="columns.length + 2" class="empty-state">暂无数据保留策略数据，可先登记保留规则</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据保留策略记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { getRetentionLink, type RuleOccupy, type Verdict } from '@/api/drill'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/retention'
const columns = ['规则编号', '数据集范围', '保留期限', '过期动作', '例外清单', '合规依据', '执行周期', '规则状态']
const actions = ['启用规则', '废止规则', '归档规则']
const stats = [{ label: '保留规则总数', value: 0 }, { label: '生效中规则', value: 0 }, { label: '已到期规则', value: 0 }]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const drillView = ref<Awaited<ReturnType<typeof getRetentionLink>> | null>(null)

function ruleOccupy(row: Row): RuleOccupy | undefined {
  return drillView.value?.规则占用明细.find((item) => item.规则编号 === row['规则编号'])
}

function verdictClass(verdict: Verdict): string {
  if (verdict === '可清理') return 'badge-clean'
  if (verdict === '延期') return 'badge-defer'
  if (verdict === '受限') return 'badge-limited'
  return 'badge-muted'
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '保留规则登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('数据保留策略动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据保留策略操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const [response, link] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      getRetentionLink().catch(() => null),
    ])
    if (!response.ok) {
      throw new Error('保留规则列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    drillView.value = link
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据保留策略列表读取失败'
  }
}

onMounted(reload)
</script>
