"""FastAPI + BUSINESS OntologyValidator."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from ontology.validator import OntologyValidator


async def validate_business_ontology(payload: dict[str, Any]) -> None:
    v = OntologyValidator.for_business()
    r = await v.validate(payload)
    if r.passed:
        return
    detail = {
        "summary":  r.summary,
        "ontology": [
            {"code": e.code, "message": e.message, "field": e.field}
            for e in r.errors[:50]
        ],
    }
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )
