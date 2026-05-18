#!/usr/bin/env python3
"""CoOps Stripe plan ↔ Price 매핑 시드 (idempotent).

``cop003_billing`` 이 만든 ``coops_billing_plans`` (id: coops-plan-*) 와
``coops_stripe_plan_mappings`` 를 env 의 Stripe Price ID 로 연결한다.

환경 변수 (비어 있으면 해당 plan 은 건너뜀):

  COOPS_STRIPE_PRICE_ID_FREE
  COOPS_STRIPE_PRICE_ID_STARTUP
  COOPS_STRIPE_PRICE_ID_SMB
  COOPS_STRIPE_PRICE_ID_ENT

사용:

  cd projects/CoOps-Platform
  export COOPS_STRIPE_PRICE_ID_ENT=price_...
  python scripts/seed_stripe_plan_mappings.py

  # Docker
  docker compose -f ../docker-compose.dev.yml exec coops-api \\
    python scripts/seed_stripe_plan_mappings.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

from sqlalchemy import select

# CoOps 앱 루트를 import path 에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import async_session_maker
from models import BillingPlan, StripePlanMapping

PLAN_ENV: list[tuple[str, str]] = [
    ("coops-plan-free", "COOPS_STRIPE_PRICE_ID_FREE"),
    ("coops-plan-startup", "COOPS_STRIPE_PRICE_ID_STARTUP"),
    ("coops-plan-smb", "COOPS_STRIPE_PRICE_ID_SMB"),
    ("coops-plan-ent", "COOPS_STRIPE_PRICE_ID_ENT"),
]


async def seed() -> int:
    upserted = 0
    async with async_session_maker() as session:
        for plan_id, env_key in PLAN_ENV:
            price_id = (os.environ.get(env_key) or "").strip()
            if not price_id:
                print(f"  skip {plan_id} ({env_key} unset)")
                continue
            plan = await session.scalar(
                select(BillingPlan).where(BillingPlan.id == plan_id)
            )
            if plan is None:
                print(f"  warn {plan_id} not in coops_billing_plans — run alembic upgrade head")
                continue
            row = await session.scalar(
                select(StripePlanMapping).where(
                    StripePlanMapping.plan_id == plan_id
                )
            )
            if row is None:
                session.add(
                    StripePlanMapping(
                        id=str(uuid.uuid4()),
                        plan_id=plan_id,
                        stripe_price_id=price_id,
                    )
                )
                print(f"  insert {plan.code} → {price_id}")
            else:
                row.stripe_price_id = price_id
                print(f"  update {plan.code} → {price_id}")
            upserted += 1
        await session.commit()
    return upserted


def main() -> None:
    print("CoOps stripe_plan_mappings seed")
    n = asyncio.run(seed())
    print(f"done ({n} mapping(s))")


if __name__ == "__main__":
    main()
