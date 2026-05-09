"""CoOps 계약 DEBATE 분석 스텁 (5-3-2 에서 확장)."""
from __future__ import annotations

import logging

log = logging.getLogger("services.contract_analyzer")


class ContractAnalyzer:
    """
    DEBATE 전략(FAST↔HEAVY) 계약 위험·조항 검토 에이전트.

    현재 단계: API·도커 검증 우선 플레이스홀더.
    다음 단계(shared-libraries): Orchestrator(DEBATE) + OntologyDomain.BUSINESS
    """

    async def analyze_placeholder(self, body_text: str) -> dict[str, str]:
        preview = (body_text or "").strip()[:280]
        log.info(
            "ContractAnalyzer 플레이스홀더 호출 길이=%s",
            len(body_text or ""),
        )
        return {
            "summary": "분석 준비됨 — Week 5-3-2 에서 DEBATE 연동 예정입니다.",
            "preview": preview,
        }
