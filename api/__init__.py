from fastapi import APIRouter

from .approvals import router as approvals_router
from .auth import router as auth_router
from .billing import router as billing_router
from .contracts import router as contracts_router
from .ontology import router as ontology_router
from .processes import router as processes_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(
    contracts_router,
    prefix="/contracts",
    tags=["contracts"],
)
api_router.include_router(
    approvals_router,
    prefix="/approvals",
    tags=["approvals"],
)
api_router.include_router(
    processes_router,
    prefix="/processes",
    tags=["processes"],
)
api_router.include_router(
    ontology_router,
    prefix="/ontology",
    tags=["ontology"],
)
api_router.include_router(
    billing_router,
    prefix="/billing",
    tags=["billing"],
)
