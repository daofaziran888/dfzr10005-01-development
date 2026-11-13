/** 到期清理演练接口封装：候选裁决、批次发起/复用、回收站与保留侧联动。 */
import { request } from '@/api/client'

export type Verdict = '可清理' | '延期' | '受限' | '未演练'
type Row = Record<string, string | number | boolean | null>

export interface RecycleWindow {
  回收记录编号: string
  删除时间: string
  可恢复截止: string
  剩余恢复天数: number | null
  窗口状态: string
}

export interface Candidate {
  策略编号: string
  生命周期策略ID: number
  表名称: string
  数据集: string
  策略保留天数: number
  归档路径: string
  清理方式: string
  策略状态: string
  裁决结果: Exclude<Verdict, '未演练'>
  风险等级: string
  风险分: number
  优先口径: string
  裁决依据: string
  命中保留规则: string | null
  命中规则保留天数: number | null
  合规依据: string | null
  例外命中: boolean
  回收窗口: RecycleWindow | null
  最近演练批次号: string | null
  最近演练裁决: Verdict | null
}

export interface CandidateView {
  生成时间: string
  保留规则版本: number
  回收窗口版本: number
  候选总数: number
  分类数量: Record<'可清理' | '延期' | '受限', number>
  候选策略: Candidate[]
  保留规则明细: Row[]
  回收记录明细: Row[]
}

export interface VersionSnapshot {
  生命周期版本: number
  保留规则版本: number
  回收窗口版本: number
}

export interface DrillBatch {
  批次号: string
  生命周期策略ID: number
  策略编号: string
  发起人: string
  发起时间: string
  状态: string
  输入指纹: string
  版本快照: VersionSnapshot
  裁决快照: Record<string, Verdict>
  裁决明细: Candidate[]
  策略快照: Row
  保留规则快照: Row[]
  回收记录快照: Row[]
  分类数量: Record<string, number>
}

export interface StartResult {
  ok: boolean
  message: string
  reused: boolean
  entry: DrillBatch
}

export interface RecycleLinkItem {
  回收记录编号: string
  表名称: string
  删除时间: string
  可恢复截止: string
  剩余恢复天数: number | null
  回收状态: string
  来源策略编号: string | null
  来源策略ID: number | null
  演练批次号: string | null
  演练裁决: Verdict
  演练裁决依据: string
  占用状态: string
  演练版本快照?: VersionSnapshot
}

export interface RetentionLinkItem {
  数据集: string
  占用批次: string[]
  涉及策略: string[]
  裁决结果: Verdict[]
  命中保留规则: string[]
  冻结版本快照: VersionSnapshot
  占用状态: string
}

export interface RuleOccupy {
  规则编号: string
  数据集范围: string
  规则状态: string
  保留天数: number
  合规依据: string
  被占用数据集: string[]
  是否被演练占用: boolean
}

async function asJson<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await request(path, init)
  if (!resp.ok) {
    let detail = `接口返回 ${resp.status}`
    try {
      detail = (await resp.json()).detail ?? detail
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    const error = new Error(detail) as Error & { status: number }
    error.status = resp.status
    throw error
  }
  return (await resp.json()) as T
}

export function getCandidates(): Promise<CandidateView> {
  return asJson<CandidateView>('/api/drills/candidates')
}

export function startDrill(policyId: number, operator: string): Promise<StartResult> {
  return asJson<StartResult>(`/api/drills/policies/${policyId}/batches`, {
    method: 'POST',
    body: JSON.stringify({ operator }),
  })
}

export function listBatches(policyId?: number): Promise<{ items: DrillBatch[]; total: number }> {
  const query = policyId ? `?policy_id=${policyId}` : ''
  return asJson(`/api/drills/batches${query}`)
}

export function getBatch(batchNo: string): Promise<DrillBatch> {
  return asJson<DrillBatch>(`/api/drills/${encodeURIComponent(batchNo)}`)
}

export function getRecycleLink(): Promise<{
  items: RecycleLinkItem[]
  total?: number
  已被演练占用: number
  回收窗口版本: number
}> {
  return asJson('/api/drills/recycle-link')
}

export function getRetentionLink(): Promise<{
  items: RetentionLinkItem[]
  规则占用明细: RuleOccupy[]
  被占用数据集数: number
  保留规则版本: number
}> {
  return asJson('/api/drills/retention-link')
}
