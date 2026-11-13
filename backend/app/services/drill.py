"""到期清理演练业务规则。

设计口径（三个页面看到的裁决必须一致，全部收敛到本模块）：

1. 演练以生命周期策略为主对象，只做模拟裁决，不删除、不修改任何业务记录。
2. 优先级规则：
   - 合规依据优先：命中生效保留规则「例外清单」的表，一律裁决为「延期」，
     合规义务高于任何清理动作；
   - 更长保留期优先：同一数据集被多条普通保留规则覆盖时，保留天数最大者为
     唯一优先结论（天数相同取规则编号靠前者），该保留天数大于生命周期策略
     保留天数时裁决为「受限」；
   - 其余数据才允许进入清理演练，裁决为「可清理」。
3. 每次演练生成一个不可变批次，冻结当时的策略、保留规则与回收窗口快照；
   规则或回收窗口变化后，旧批次按原先口径留档，新批次按新版本重新计算。
4. 同一策略重复发起且输入口径未变时复用原批次；两个管理员并发争抢同一策略，
   后到请求被拒绝占用批次（409），所有结果回写审计清单。
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import date, datetime
from typing import Any

from app.store import store

LIFECYCLE_MODULE = "lifecycle"
RETENTION_MODULE = "retention"
RECYCLE_MODULE = "recycle"
AUDIT_MODULE = "audit"

VERDICT_CLEAN = "可清理"
VERDICT_DEFER = "延期"
VERDICT_LIMITED = "受限"
VERDICT_NOT_DONE = "未演练"
VERDICT_ORDER = [VERDICT_CLEAN, VERDICT_DEFER, VERDICT_LIMITED]

# 风险分：可清理（真会搬走/删掉数据）> 受限（规则冲突需处理）> 延期（受保护最安全）
RISK_WEIGHT = {VERDICT_CLEAN: 100, VERDICT_LIMITED: 60, VERDICT_DEFER: 20}
RISK_HIGH = 85
RISK_MIDDLE = 40

ACTIVE_RULE_STATUS = "生效中"
# 回收站里仍可恢复的记录才参与恢复窗口计算
RECOVERABLE_RECYCLE_STATUS = {"待恢复"}


class DrillConflictError(Exception):
    """同一策略已有演练在途，后到的并发请求被拒绝占用批次。"""


def _today() -> date:
    return date.today()


def _to_int(value: Any) -> int:
    """保留天数在示例数据里是 int，历史脏数据可能是字符串，统一兜底解析。"""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "")
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def _iso_to_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    """对一组业务行计算稳定指纹，用于识别规则/窗口是否发生变化。"""
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class DrillService:
    """演练批次、版本快照与联动裁决都在这里维护；路由层不做业务判断。"""

    def __init__(self) -> None:
        self._batches: list[dict[str, Any]] = []
        self._seq = 0
        # 同一策略串行化：非阻塞锁保证并发演练只有一个能占用批次
        self._policy_locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        # 每个模块规则版本注册表：指纹变了才递增，旧批次继续引用旧版本号
        self._versions: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ 版本

    def _module_version(self, module: str) -> dict[str, Any]:
        """惰性登记模块版本：指纹未变沿用原版本号，变化后递增出新版本。"""
        rows = store.rows(module)
        current = _fingerprint(rows)
        registered = self._versions.get(module)
        if registered is None or registered["fingerprint"] != current:
            next_no = 1 if registered is None else int(registered["version"]) + 1
            registered = {"version": next_no, "fingerprint": current}
            self._versions[module] = registered
        return {"version": registered["version"], "fingerprint": registered["fingerprint"]}

    def input_fingerprint(self, policy: dict[str, Any]) -> str:
        """本次裁决输入口径指纹：策略自身 + 全部生效保留规则 + 回收窗口。"""
        parts = [
            {"module": LIFECYCLE_MODULE, "rows": [policy]},
            {"module": RETENTION_MODULE,
             "rows": [row for row in store.rows(RETENTION_MODULE)
                      if row.get("规则状态") == ACTIVE_RULE_STATUS
                      or row.get("status") == ACTIVE_RULE_STATUS]},
            {"module": RECYCLE_MODULE, "rows": store.rows(RECYCLE_MODULE)},
        ]
        return _fingerprint(parts)

    # ------------------------------------------------------------------ 裁决

    @staticmethod
    def _matching_rules(dataset: str) -> list[dict[str, Any]]:
        rules = []
        for row in store.rows(RETENTION_MODULE):
            if row.get("status") != ACTIVE_RULE_STATUS and row.get("规则状态") != ACTIVE_RULE_STATUS:
                continue
            scopes = [part.strip() for part in str(row.get("数据集范围", "")).split(",") if part.strip()]
            if dataset in scopes:
                rules.append(row)
        return rules

    @staticmethod
    def _recycle_window(table_name: str) -> dict[str, Any] | None:
        """查同表仍在回收保护期内的回收记录，返回尚余恢复天数。"""
        today = _today()
        for row in store.rows(RECYCLE_MODULE):
            if row.get("表名称") != table_name:
                continue
            if row.get("status") not in RECOVERABLE_RECYCLE_STATUS:
                continue
            deadline = _iso_to_date(row.get("可恢复期"))
            remaining = (deadline - today).days if deadline else None
            return {
                "回收记录编号": row.get("记录编号"),
                "删除时间": row.get("删除时间"),
                "可恢复截止": row.get("可恢复期"),
                "剩余恢复天数": remaining,
                "窗口状态": "窗口内" if remaining is not None and remaining >= 0 else "已过窗口",
            }
        return None

    def adjudicate(self, policy: dict[str, Any]) -> dict[str, Any]:
        """对单条生命周期策略给出唯一裁决结论。

        返回结构同时携带保留规则意见与回收窗口，生命周期策略始终是主对象：
        保留规则只能产出「延期/受限」意见，不能改写策略编号与策略事实。
        """
        dataset = str(policy.get("数据集", "")).strip()
        table_name = str(policy.get("表名称", "")).strip()
        life_days = _to_int(policy.get("保留天数"))
        rules = self._matching_rules(dataset)

        matched_rule: dict[str, Any] | None = None
        exception_hit = False
        basis = ""
        basis_priority = ""

        # 优先级一：合规依据优先 —— 任一命中规则的例外清单包含本表即延期
        for rule in rules:
            exceptions = [item.strip() for item in str(rule.get("例外清单", "")).split(",") if item.strip()]
            if table_name in exceptions:
                matched_rule = rule
                exception_hit = True
                basis_priority = "合规依据优先"
                basis = f"命中 {rule.get('规则编号')} 例外清单（依据：{rule.get('合规依据')}），法定留存禁止清理"
                break

        # 优先级二：更长保留期优先 —— 取保留天数最大的唯一规则
        if matched_rule is None and rules:
            winner = max(
                rules,
                key=lambda item: (_to_int(item.get("保留天数")), -int(item.get("id", 0))),
            )
            matched_rule = winner
            basis_priority = "更长保留期优先"
            winner_days = _to_int(winner.get("保留天数"))
            if winner_days > life_days:
                basis = (f"{winner.get('规则编号')} 保留 {winner_days} 天 > 策略保留 {life_days} 天，"
                         f"按最长保留期规则限制清理")
            else:
                basis = (f"{winner.get('规则编号')} 保留 {winner_days} 天，未超过策略保留 {life_days} 天，"
                         f"不构成限制")

        if exception_hit:
            verdict = VERDICT_DEFER
        elif matched_rule is not None and _to_int(matched_rule.get("保留天数")) > life_days:
            verdict = VERDICT_LIMITED
        else:
            verdict = VERDICT_CLEAN
            if not basis:
                basis = "无例外命中、无更长保留期规则，允许进入清理演练（演练不删除业务记录）"

        recycle_window = self._recycle_window(table_name)
        risk_score = RISK_WEIGHT[verdict]
        if risk_score >= RISK_HIGH:
            risk_level = "高"
        elif risk_score >= RISK_MIDDLE:
            risk_level = "中"
        else:
            risk_level = "低"

        return {
            "策略编号": policy.get("策略编号"),
            "生命周期策略ID": policy.get("id"),
            "表名称": table_name,
            "数据集": dataset,
            "策略保留天数": life_days,
            "归档路径": policy.get("归档路径"),
            "清理方式": policy.get("清理方式"),
            "策略状态": policy.get("策略状态") or policy.get("status"),
            "裁决结果": verdict,
            "风险等级": risk_level,
            "风险分": risk_score,
            "优先口径": basis_priority or "默认口径",
            "裁决依据": basis,
            "命中保留规则": matched_rule.get("规则编号") if matched_rule else None,
            "命中规则保留天数": _to_int(matched_rule.get("保留天数")) if matched_rule else None,
            "合规依据": matched_rule.get("合规依据") if matched_rule else None,
            "例外命中": exception_hit,
            "回收窗口": recycle_window,
        }

    # --------------------------------------------------------------- 候选视图

    def candidate_view(self) -> dict[str, Any]:
        """联动裁决视图：候选策略 + 数据集保留规则 + 回收记录，一次给齐。"""
        policies = store.rows(LIFECYCLE_MODULE)
        candidates = [self.adjudicate(policy) for policy in policies]
        # 按风险排列：风险分降序，同分按策略编号稳定排序
        candidates.sort(key=lambda item: (-int(item["风险分"]), str(item["策略编号"])))

        counts = {verdict: 0 for verdict in VERDICT_ORDER}
        for item in candidates:
            counts[item["裁决结果"]] += 1

        latest_by_policy = self._latest_batch_by_policy()
        for item in candidates:
            batch = latest_by_policy.get(int(item["生命周期策略ID"]))
            item["最近演练批次号"] = batch["批次号"] if batch else None
            item["最近演练裁决"] = batch["裁决快照"].get(item["策略编号"]) if batch else None

        retention_meta = self._module_version(RETENTION_MODULE)
        recycle_meta = self._module_version(RECYCLE_MODULE)
        return {
            "生成时间": datetime.now().isoformat(timespec="seconds"),
            "保留规则版本": retention_meta["version"],
            "回收窗口版本": recycle_meta["version"],
            "候选总数": len(candidates),
            "分类数量": counts,
            "候选策略": candidates,
            "保留规则明细": [dict(row) for row in store.rows(RETENTION_MODULE)],
            "回收记录明细": [dict(row) for row in store.rows(RECYCLE_MODULE)],
        }

    # --------------------------------------------------------------- 演练发起

    def _get_lock(self, policy_id: int) -> threading.Lock:
        with self._locks_guard:
            lock = self._policy_locks.get(policy_id)
            if lock is None:
                lock = threading.Lock()
                self._policy_locks[policy_id] = lock
            return lock

    def _latest_batch_by_policy(self) -> dict[int, dict[str, Any]]:
        latest: dict[int, dict[str, Any]] = {}
        for batch in self._batches:
            latest[int(batch["生命周期策略ID"])] = batch
        return latest

    def start_drill(self, policy_id: int, operator: str) -> tuple[dict[str, Any], bool]:
        """发起一次演练，返回 (批次, 是否新建)。

        - 并发：同策略已有演练在途 → DrillConflictError，后到请求拒绝占用批次；
        - 复用：输入口径（策略/规则/回收窗口指纹）未变 → 复用原批次结论；
        - 变化：任一来源版本变化 → 新建批次重算，旧批次原样留档。
        """
        policy = store.find(LIFECYCLE_MODULE, policy_id)
        if policy is None:
            raise ValueError(f"生命周期策略 {policy_id} 不存在或已归档")

        lock = self._get_lock(policy_id)
        # 非阻塞抢占：抢不到说明同策略演练正在进行，后到请求不等待、直接拒绝
        if not lock.acquire(blocking=False):
            holder = next(
                (b["发起人"] for b in reversed(self._batches)
                 if int(b["生命周期策略ID"]) == policy_id),
                "其他管理员",
            )
            self._write_audit(policy, operator, "并发拒绝", None,
                              f"策略 {policy.get('策略编号')} 演练批次被 {holder} 占用，后到请求拒绝")
            raise DrillConflictError(
                f"策略 {policy.get('策略编号')} 的演练批次已被其他管理员占用，请稍后查看原批次结论"
            )

        try:
            fingerprint = self.input_fingerprint(policy)
            existing = next(
                (b for b in reversed(self._batches)
                 if int(b["生命周期策略ID"]) == policy_id and b["输入指纹"] == fingerprint),
                None,
            )
            if existing is not None:
                # 复用未产生新状态，不重复写审计；批次历史本身保留完整复用轨迹
                return existing, False

            self._seq += 1
            batch_no = f"DRL-{self._seq:04d}"
            result = self.adjudicate(policy)
            retention_meta = self._module_version(RETENTION_MODULE)
            recycle_meta = self._module_version(RECYCLE_MODULE)
            lifecycle_meta = self._module_version(LIFECYCLE_MODULE)
            batch = {
                "批次号": batch_no,
                "生命周期策略ID": policy_id,
                "策略编号": policy.get("策略编号"),
                "发起人": operator,
                "发起时间": datetime.now().isoformat(timespec="seconds"),
                "状态": "已完成",
                "输入指纹": fingerprint,
                "版本快照": {
                    "生命周期版本": lifecycle_meta["version"],
                    "保留规则版本": retention_meta["version"],
                    "回收窗口版本": recycle_meta["version"],
                },
                "裁决快照": {result["策略编号"]: result["裁决结果"]},
                "裁决明细": [result],
                "策略快照": dict(policy),
                "保留规则快照": [dict(row) for row in store.rows(RETENTION_MODULE)],
                "回收记录快照": [dict(row) for row in store.rows(RECYCLE_MODULE)],
                "分类数量": {result["裁决结果"]: 1},
                "占用中": False,
            }
            self._batches.append(batch)
            self._write_audit(policy, operator, "演练完成", batch,
                              f"批次 {batch_no} 裁决为「{result['裁决结果']}」（{result['优先口径']}）")
            return batch, True
        finally:
            lock.release()

    # ------------------------------------------------------------------ 查询

    def list_batches(self, policy_id: int | None = None) -> list[dict[str, Any]]:
        batches = [self._public_batch(b) for b in self._batches]
        if policy_id is not None:
            batches = [b for b in batches if int(b["生命周期策略ID"]) == policy_id]
        return batches

    def get_batch(self, batch_no: str) -> dict[str, Any] | None:
        for batch in self._batches:
            if batch["批次号"] == batch_no:
                return self._public_batch(batch)
        return None

    @staticmethod
    def _public_batch(batch: dict[str, Any]) -> dict[str, Any]:
        """对外视图不带内部占用标记，保留完整快照以支撑旧结论追溯。"""
        view = dict(batch)
        view.pop("占用中", None)
        return view

    # ----------------------------------------------------- 回收站 / 保留侧联动

    def recycle_link_view(self) -> dict[str, Any]:
        """回收站视角：每条回收记录能看懂演练来源策略与可恢复截止时间。"""
        latest = self._latest_batch_by_policy()
        policies = store.rows(LIFECYCLE_MODULE)
        policy_by_table = {str(p.get("表名称")): p for p in policies}
        items: list[dict[str, Any]] = []
        today = _today()

        for record in store.rows(RECYCLE_MODULE):
            table_name = str(record.get("表名称", ""))
            policy = policy_by_table.get(table_name)
            deadline = _iso_to_date(record.get("可恢复期"))
            remaining = (deadline - today).days if deadline else None
            entry: dict[str, Any] = {
                "回收记录编号": record.get("记录编号"),
                "表名称": table_name,
                "删除时间": record.get("删除时间"),
                "可恢复截止": record.get("可恢复期"),
                "剩余恢复天数": remaining,
                "回收状态": record.get("status"),
                "来源策略编号": None,
                "来源策略ID": None,
                "演练批次号": None,
                "演练裁决": VERDICT_NOT_DONE,
                "演练裁决依据": "该表尚未发起到期清理演练",
                "占用状态": "未被演练占用",
            }
            if policy is not None:
                entry["来源策略编号"] = policy.get("策略编号")
                entry["来源策略ID"] = policy.get("id")
                batch = latest.get(int(policy["id"]))
                if batch is not None:
                    detail = next(
                        (d for d in batch["裁决明细"] if d["表名称"] == table_name), None
                    )
                    entry["演练批次号"] = batch["批次号"]
                    entry["演练裁决"] = batch["裁决快照"].get(policy.get("策略编号"), VERDICT_NOT_DONE)
                    entry["演练裁决依据"] = detail["裁决依据"] if detail else ""
                    entry["演练版本快照"] = batch["版本快照"]
                    entry["占用状态"] = f"被批次 {batch['批次号']} 占用（结论已冻结）"
            items.append(entry)

        return {
            "生成时间": datetime.now().isoformat(timespec="seconds"),
            "回收窗口版本": self._module_version(RECYCLE_MODULE)["version"],
            "总记录数": len(items),
            "已被演练占用": sum(1 for item in items if item["演练批次号"]),
            "items": items,
        }

    def retention_link_view(self) -> dict[str, Any]:
        """数据保留侧视角：哪些数据集被本次演练占用，以及规则给出的意见。"""
        latest = self._latest_batch_by_policy()
        occupied_datasets: dict[str, dict[str, Any]] = {}
        for batch in self._batches:
            for detail in batch["裁决明细"]:
                dataset = detail["数据集"]
                slot = occupied_datasets.setdefault(dataset, {
                    "数据集": dataset,
                    "占用批次": set(),
                    "涉及策略": set(),
                    "裁决结果": set(),
                    "命中规则": set(),
                    "最近版本快照": None,
                })
                slot["占用批次"].add(batch["批次号"])
                slot["涉及策略"].add(detail["策略编号"])
                slot["裁决结果"].add(detail["裁决结果"])
                if detail.get("命中保留规则"):
                    slot["命中规则"].add(detail["命中保留规则"])
                slot["最近版本快照"] = batch["版本快照"]

        items: list[dict[str, Any]] = []
        for dataset in sorted(occupied_datasets):
            slot = occupied_datasets[dataset]
            items.append({
                "数据集": dataset,
                "占用批次": sorted(slot["占用批次"]),
                "涉及策略": sorted(slot["涉及策略"]),
                "裁决结果": sorted(slot["裁决结果"]),
                "命中保留规则": sorted(slot["命中规则"]),
                "冻结版本快照": slot["最近版本快照"],
                "占用状态": f"被 {len(slot['占用批次'])} 个演练批次占用",
            })

        # 保留规则自身视角：每条规则覆盖的数据集是否正被演练占用
        rule_items: list[dict[str, Any]] = []
        for rule in store.rows(RETENTION_MODULE):
            scopes = [part.strip() for part in str(rule.get("数据集范围", "")).split(",") if part.strip()]
            hit_datasets = [scope for scope in scopes if scope in occupied_datasets]
            rule_items.append({
                "规则编号": rule.get("规则编号"),
                "数据集范围": rule.get("数据集范围"),
                "规则状态": rule.get("规则状态") or rule.get("status"),
                "保留天数": _to_int(rule.get("保留天数")),
                "合规依据": rule.get("合规依据"),
                "被占用数据集": hit_datasets,
                "是否被演练占用": bool(hit_datasets),
            })

        return {
            "生成时间": datetime.now().isoformat(timespec="seconds"),
            "保留规则版本": self._module_version(RETENTION_MODULE)["version"],
            "被占用数据集数": len(items),
            "items": items,
            "规则占用明细": rule_items,
        }

    # ------------------------------------------------------------------ 审计

    def _write_audit(
        self,
        policy: dict[str, Any],
        operator: str,
        change_type: str,
        batch: dict[str, Any] | None,
        message: str,
    ) -> None:
        """把演练状态结果回写到审计清单（只追加，不改动业务记录）。"""
        rows = store.rows(AUDIT_MODULE)
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        next_seq = max(
            (int(str(row.get("记录编号", "")).split("-")[-1]) for row in rows
             if str(row.get("记录编号", "")).startswith("AUDI-")),
            default=0,
        ) + 1
        before = ""
        after = message
        if batch is not None:
            before = f"输入指纹 {batch.get('输入指纹', '')}"
            after = f"{message}；版本快照 {json.dumps(batch.get('版本快照', {}), ensure_ascii=False)}"
        rows.append({
            "id": next_id,
            "status": "已记录",
            "pending": True,
            "abnormal": change_type == "并发拒绝",
            "记录编号": f"AUDI-{next_seq:04d}",
            "变更对象": f"到期清理演练/{policy.get('策略编号')}",
            "变更类型": change_type,
            "变更前值": before,
            "变更后值": after,
            "操作人": operator or "未知管理员",
            "操作时间": datetime.now().isoformat(timespec="seconds"),
            "复核状态": "待复核" if change_type != "并发拒绝" else "冲突待裁定",
        })


drill_service = DrillService()
