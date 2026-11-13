"""到期清理演练接口：以生命周期策略为主对象的联动裁决视图。

路由顺序注意：固定路径（candidates/batches/recycle-link/retention-link）必须
排在动态路径 /{batch_no} 之前，否则会被动态参数吞掉。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.drill import DrillConflictError, drill_service

router = APIRouter(prefix="/api/drills", tags=["到期清理演练"])


class DrillStartPayload(BaseModel):
    """发起演练时提交的操作人信息，用于并发占用与审计回写。"""

    operator: str = Field(default="值班管理员", description="发起演练的管理员")


@router.get("/candidates")
def candidate_view() -> dict[str, Any]:
    """联动裁决视图：候选策略按风险排列，给出可清理/延期/受限三类结果与数量。"""
    return drill_service.candidate_view()


@router.post("/policies/{policy_id}/batches")
def start_drill(policy_id: int, payload: DrillStartPayload) -> dict[str, Any]:
    """对单条生命周期策略发起演练。

    演练不删除任何业务记录；口径未变复用原批次，口径变化新建批次重算；
    两个管理员并发争抢同一策略时，后到请求被拒绝占用批次（409）。
    """
    try:
        batch, created = drill_service.start_drill(policy_id, payload.operator.strip() or "值班管理员")
    except DrillConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "ok": True,
        "message": "演练批次已创建并冻结结论" if created else "输入口径未变，已复用原演练批次结论",
        "reused": not created,
        "entry": batch,
    }


@router.get("/batches")
def list_batches(policy_id: int | None = None) -> dict[str, Any]:
    """演练批次历史：旧批次按原先规则留档，可逐条追溯版本快照。"""
    items = drill_service.list_batches(policy_id)
    return {"items": items, "total": len(items)}


@router.get("/recycle-link")
def recycle_link_view() -> dict[str, Any]:
    """回收站联动：每条回收记录的来源策略、演练批次与可恢复截止时间。"""
    return drill_service.recycle_link_view()


@router.get("/retention-link")
def retention_link_view() -> dict[str, Any]:
    """数据保留侧联动：哪些数据集被本次演练占用，规则给出的是何种意见。"""
    return drill_service.retention_link_view()


@router.get("/{batch_no}")
def get_batch(batch_no: str) -> dict[str, Any]:
    """读取单个演练批次的冻结结论与当时快照。"""
    batch = drill_service.get_batch(batch_no)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"演练批次 {batch_no} 不存在")
    return batch
