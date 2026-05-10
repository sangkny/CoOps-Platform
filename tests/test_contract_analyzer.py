"""계약 DEBATE 분석 단위 테스트."""
from __future__ import annotations

from datetime import date

import pytest


def test_contract_parse_levels() -> None:
    from services.contract_analyzer import parse_contract_analysis

    p = parse_contract_analysis(
        "**Risk**: critical\n"
        "- IP\n- SLA\n",
    )
    assert p["risk_level"] == "critical"


@pytest.mark.asyncio
async def test_business_dependency_high_risk_approver() -> None:
    from ontology.validator import OntologyValidator

    vr = await OntologyValidator.for_business().validate(
        {
            "contract_id":    "CON-20260509",
            "requester_id":    "TST",
            "request_date":    date.today().isoformat(),
            "description":    "계약 DEBATE 결과 요약 " * 3,
            "risk_level":     "high",
            "approver_id":    "MGR-X",
        },
    )
    assert vr.passed is True


@pytest.mark.asyncio
async def test_business_dependency_high_missing_approver() -> None:
    from ontology.validator import OntologyValidator

    vr = await OntologyValidator.for_business().validate(
        {
            "contract_id":    "CON-20260509",
            "requester_id":    "TST",
            "request_date":    date.today().isoformat(),
            "description":    "요약입니다",
            "risk_level":     "high",
        },
    )
    assert vr.passed is False
