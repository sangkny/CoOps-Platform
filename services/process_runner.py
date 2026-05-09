"""업무 프로세스 실행 스텁 — BUSINESS Ontology 연계 예정."""
from __future__ import annotations

import logging

log = logging.getLogger("services.process_runner")


class ProcessRunner:
    """BUSINESS OntologyValidator + 단계 플로우 (스캐폴드)."""

    async def run_placeholder(self, workflow_json: str | None, name: str) -> dict:
        log.info("ProcessRunner 플레이스홀더 name=%s", name)
        return {
            "ok": True,
            "message": "프로세스 러너 스켈레톤 — Ontology 검증 및 단계 실행은 후속 추가.",
            "workflow_len": len(workflow_json or ""),
        }
