<template>
  <section class="page" data-module="recycle">
    <header class="page-head">
      <div>
        <h2>数据回收站管理</h2>
        <p class="page-desc">维护数据回收的删除溯源、恢复窗口与清理计划；联动到期清理演练，看懂每条记录的来源策略、占用批次与可恢复截止时间。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记回收记录</button>
        <button class="btn" type="button" @click="exportRows">导出数据回收站清单</button>
      </div>
    </header>

    <div class="version-bar">
      <span>演练联动版本：<strong>回收窗口 v{{ drillView?.回收窗口版本 ?? '—' }}</strong></span>
      <span>已被演练占用记录：<strong>{{ drillView?.已被演练占用 ?? 0 }}</strong> / {{ drillView?.items.length ?? 0 }}</span>
      <button class="btn" type="button" @click="reload">刷新演练联动</button>
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
          <th>演练来源策略</th>
          <th>演练批次 / 裁决</th>
          <th>占用状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <template v-if="linkOf(row)?.来源策略编号">
              <strong>{{ linkOf(row)?.来源策略编号 }}</strong>
              <div class="inline-note">截止 {{ linkOf(row)?.可恢复截止 }} · 尚余 {{ linkOf(row)?.剩余恢复天数 ?? '—' }} 天</div>
            </template>
            <span v-else class="inline-note">无对应生命周期策略</span>
          </td>
          <td>
            <template v-if="linkOf(row)?.演练批次号">
              <RouterLink class="link" to="/lifecycle">{{ linkOf(row)?.演练批次号 }}</RouterLink>
              <div>
                <span class="badge" :class="verdictClass(linkOf(row)?.演练裁决 ?? '未演练')">{{ linkOf(row)?.演练裁决 }}</span>
              </div>
              <div class="reason-cell">{{ linkOf(row)?.演练裁决依据 }}</div>
            </template>
            <span v-else class="inline-note">{{ linkOf(row)?.演练裁决 ?? '未演练' }}</span>
          </td>
          <td>
            <span :class="linkOf(row)?.演练批次号 ? '' : 'inline-note'">{{ linkOf(row)?.占用状态 ?? '—' }}</span>
            <div v-if="linkOf(row)?.演练版本快照" class="snapshot-box">
              保留规则 v{{ linkOf(row)?.演练版本快照?.保留规则版本 }} · 回收窗口 v{{ linkOf(row)?.演练版本快照?.回收窗口版本 }}
            </div>
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
          <td :colspan="columns.length + 4" class="empty-state">暂无数据回收站数据，可先登记回收记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据回收站记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { getRecycleLink, type RecycleLinkItem, type Verdict } from '@/api/drill'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/recycle'
const columns = ['记录编号', '表名称', '删除时间', '回收原因', '数据大小', '可恢复期', '恢复状态', '清理时间']
const actions = ['恢复数据', '永久清理', '延期保留']
const stats = [{ label: '回收记录总数', value: 0 }, { label: '待恢复记录', value: 0 }, { label: '已清理记录', value: 0 }]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const drillView = ref<{ items: RecycleLinkItem[]; 已被演练占用: number; 回收窗口版本: number } | null>(null)

function linkOf(row: Row): RecycleLinkItem | undefined {
  return drillView.value?.items.find((item) => item.回收记录编号 === row['记录编号'])
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
  errorMessage.value = '回收记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('数据回收站动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据回收站操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const [response, link] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      getRecycleLink().catch(() => null),
    ])
    if (!response.ok) {
      throw new Error('回收记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    drillView.value = link
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据回收站列表读取失败'
  }
}

onMounted(reload)
</script>
