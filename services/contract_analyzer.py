"""계약서 DEBATE 분석 + BUSINESS Ontology + Lore 영속화."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date
from typing import Any

from agents.orchestrator import Orchestrator, OrchestraStrategy
from ontology.base import OntologyDomain
from ontology.validator import OntologyValidator
from sqlalchemy.ext.asyncio import AsyncSession

from models.business import ContractAnalysisRecord
from schemas.business import validate_contract_number_format

log = logging.getLogger("services.contract_analyzer")


def parse_contract_analysis(output_text: str) -> dict[str, Any]:
    """DEBATE 출력에서 위험도·불릿 항목을 경량 파싱."""
    t      = output_text or ""
    tl     = t.lower()
    chosen = "low"
    for level in ("critical", "high", "medium"):
        if re.search(rf"\b{re.escape(level)}\b", tl):
            chosen = level
            break
    bullets = re.findall(r"^\s*(?:[-*•]|\d+\.)\s*(.+)$", t, flags=re.MULTILINE)
    return {
        "risk_level":  chosen,
        "summary":     t.strip()[:500],
        "risk_items":  [b.strip() for b in bullets[:6]],
    }


def lore_to_serializable(entries: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in entries or []:
        if isinstance(e, dict):
            out.append(dict(e))
            continue
        if not getattr(e, "task_id", None):
            continue
        agent_raw = getattr(e, "agent", None)
        agent_val = getattr(agent_raw, "value", None) if agent_raw is not None else None
        if agent_val is None and agent_raw is not None:
            agent_val = str(agent_raw)
        out.append(
            {
                "task_id":    e.task_id,
                "agent":      agent_val,
                "action":     e.action,
                "decision":   e.decision,
                "model_used": e.model_used,
                "passed":     e.passed,
                "iteration":  e.iteration,
                "timestamp":  getattr(e, "timestamp", ""),
            },
        )
    return out


class ContractAnalyzer:
    """Ontology 검증 후 Orchestrator DEBATE 실행."""

    async def analyze(
        self,
        db: AsyncSession,
        contract_text: str,
        contract_number: str,
    ) -> dict[str, Any]:
        cn = validate_contract_number_format(contract_number)

        prelude = (
            contract_text.strip()[:2000]
            or "계약 텍스트가 비어있습니다 — 조항번호·납품범위·지급조건만 요약 검토합니다."
        )
        input_chk = await OntologyValidator.for_business().validate(
            {
                "contract_id":    cn,
                "requester_id":    "AI-CONTRACT-ANALYSIS",
                "request_date":    date.today().isoformat(),
                "description":    prelude[:4000],
            },
        )
        if not input_chk.passed:
            raise ValueError(f"계약번호/입력 Ontology 오류: {input_chk.summary}")

        orch = Orchestrator(
            domain=OntologyDomain.BUSINESS,
            strategy=OrchestraStrategy.DEBATE,
            max_iterations=2,
        )
        res    = await orch.execute(f"계약서 분석:\n{prelude}")
        debate = str(res.output or "").strip()

        parsed   = parse_contract_analysis(debate)
        risk     = parsed["risk_level"]

        finale: dict[str, Any] = {
            "contract_id":    cn,
            "requester_id":    "AI-CONTRACT-ANALYSIS",
            "request_date":    date.today().isoformat(),
            "description":    debate[:7900],
            "risk_level":     risk,
        }
        if risk in {"high", "critical"}:
            finale["approver_id"] = "STAKEHOLDER-CHAIN-REVIEW"

        fv = await OntologyValidator.for_business().validate(finale)
        lore_list = lore_to_serializable(res.lore)

        rec = ContractAnalysisRecord(
            id=str(uuid.uuid4()),
            contract_number=cn,
            debate_output=debate[:65500],
            risk_level=risk,
            ontology_passed=fv.passed,
            ontology_errors_json=json.dumps(
                [e.message for e in fv.errors][:20],
                ensure_ascii=False,
            ),
            lore_json=json.dumps(lore_list, ensure_ascii=False),
        )
        db.add(rec)
        await db.flush()

        log.info(
            "contract 분석 저장 id=%s risk=%s onto=%s",
            rec.id[:8],
            risk,
            fv.passed,
        )
        return {
            "contract_number":        cn,
            "summary":                parsed["summary"],
            "risk_level":             risk,
            "risk_highlights":        parsed["risk_items"],
            "debate_output_excerpt":  debate[:2400],
            "ontology_passed":        fv.passed,
            "ontology_errors":        [e.message for e in fv.errors][:12],
            "lore":                   lore_list,
            "record_id":              rec.id,
        }