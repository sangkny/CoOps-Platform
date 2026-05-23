"""결재 요청 — 4-에이전트 결정 분기 (legacy Ontology 검증 유지)."""
from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any

log = logging.getLogger("services.approval_pipeline")


def _auto_action_enabled() -> bool:
    return os.getenv("AGENT_FOUR_AGENT_AUTO_ACTION", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


async def process_four_agent_decision(
    approval: Any,
    *,
    contract_number: str,
    amount: Decimal | None,
    description: str | None,
) -> dict:
    """
    four_agent 모드일 때 Advocate/Critic 결정.
    AGENT_FOUR_AGENT_AUTO_ACTION=1 이면 approve/reject/status 갱신.
    기본은 audit trail + lore만 기록 (status=pending 유지).
    """
    from agents.feature_flags import AgentFeatureFlags
    from agents.pipeline import AgentPipeline

    approval_id = str(approval.id)
    if not AgentFeatureFlags.is_four_agent_enabled(approval_id):
        return {"mode": "legacy", "skipped": True}

    artifact = {
        "approval_id": approval_id,
        "amount": str(amount) if amount is not None else None,
        "description": description or "",
        "requester": approval.requester_id,
        "contract_number": contract_number,
    }
    pipe = AgentPipeline(domain="business", task_id=f"coops-{approval_id[:8]}")
    try:
        pr = await pipe.run_decision(artifact, "business", request_id=approval_id)
    except Exception as exc:
        log.warning("four_agent approval decision failed: %s", exc)
        return {"mode": "legacy", "error": str(exc)[:200]}

    decision = pr.decision.decision
    audit = dict(pr.audit_trail or {})
    audit["decision"] = decision
    audit["mode"] = pr.mode

    if _auto_action_enabled():
        if decision == "APPROVE":
            approval.status = "approved"
            approval.finalized = True
            approval.actor_id = approval.actor_id or "four_agent_auto"
            audit["auto_action"] = "approved"
        elif decision == "REJECT":
            approval.status = "rejected"
            approval.finalized = True
            approval.comment = (audit.get("critic_summary") or "four_agent REJECT")[:500]
            approval.actor_id = approval.actor_id or "four_agent_auto"
            audit["auto_action"] = "rejected"
        else:
            approval.status = "revision_required"
            audit["auto_action"] = "escalate"
    else:
        audit["auto_action"] = "none"

    return audit
