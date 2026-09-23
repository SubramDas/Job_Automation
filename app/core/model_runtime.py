"""Deterministic model routing contracts for Phase 04.

No provider call is made here. The router records which model would be used, applies the
configured repair/escalation limits, and stops with review when privacy or budget policy
does not allow a route.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import _read_json
from app.storage.space import stable_json, utc_now


@dataclass(frozen=True)
class ModelRoute:
    agent_id: str
    stage: str
    selected_model: str | None
    route_status: str
    repair_attempt: int
    escalation_attempt: int
    output_schema: dict[str, Any]
    input_hash: str
    model_version_recorded_at: str
    estimated_tokens: int
    estimated_cost: float


@dataclass
class ModelUsageLedger:
    configured_budget: float | None
    total_estimated_cost: float = 0.0

    def can_spend(self, amount: float) -> bool:
        return self.configured_budget is None or self.total_estimated_cost + amount <= self.configured_budget

    def record(self, amount: float) -> None:
        self.total_estimated_cost += amount


class ModelRouter:
    """Select configured agent models while respecting Phase 04 synthetic restrictions."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.models = _read_json(project_root / "config" / "models.example.json")
        self.policies = _read_json(project_root / "config" / "policies.example.json")
        budget = self.policies["limits"].get("model_cost_budget")
        self.ledger = ModelUsageLedger(configured_budget=budget)

    def route(
        self,
        *,
        agent_id: str,
        stage: str,
        payload: dict[str, Any],
        output_schema: dict[str, Any],
        repair_attempt: int = 0,
        escalation_attempt: int = 0,
    ) -> ModelRoute:
        agent_config = self.models["agents"][agent_id]
        if repair_attempt > agent_config["max_schema_repairs"]:
            return self._stop(agent_id, stage, payload, output_schema, repair_attempt, escalation_attempt, "schema_repair_exhausted")

        candidates = [agent_config["default_model"], *agent_config["fallback_models"]]
        if escalation_attempt >= len(candidates):
            return self._stop(agent_id, stage, payload, output_schema, repair_attempt, escalation_attempt, "escalation_exhausted")

        estimated_tokens = self._estimate_tokens(payload)
        estimated_cost = self._estimate_cost(candidates[escalation_attempt], estimated_tokens)
        if not self.ledger.can_spend(estimated_cost):
            return self._stop(agent_id, stage, payload, output_schema, repair_attempt, escalation_attempt, "budget_exhausted")

        if not self.models["provider"].get("personal_data_allowed", False) and payload.get("contains_personal_data"):
            return self._stop(agent_id, stage, payload, output_schema, repair_attempt, escalation_attempt, "privacy_review_required")

        self.ledger.record(estimated_cost)
        return ModelRoute(
            agent_id=agent_id,
            stage=stage,
            selected_model=candidates[escalation_attempt],
            route_status="selected_synthetic_no_provider_call",
            repair_attempt=repair_attempt,
            escalation_attempt=escalation_attempt,
            output_schema=output_schema,
            input_hash=self._hash(payload),
            model_version_recorded_at=utc_now(),
            estimated_tokens=estimated_tokens,
            estimated_cost=estimated_cost,
        )

    def _stop(
        self,
        agent_id: str,
        stage: str,
        payload: dict[str, Any],
        output_schema: dict[str, Any],
        repair_attempt: int,
        escalation_attempt: int,
        status: str,
    ) -> ModelRoute:
        return ModelRoute(
            agent_id=agent_id,
            stage=stage,
            selected_model=None,
            route_status=status,
            repair_attempt=repair_attempt,
            escalation_attempt=escalation_attempt,
            output_schema=output_schema,
            input_hash=self._hash(payload),
            model_version_recorded_at=utc_now(),
            estimated_tokens=self._estimate_tokens(payload),
            estimated_cost=0.0,
        )

    def _estimate_tokens(self, payload: dict[str, Any]) -> int:
        # Conservative deterministic estimate for routing/budget tests. Real billing comes
        # from provider usage once provider calls are approved.
        return max(1, len(stable_json(payload)) // 4)

    def _estimate_cost(self, model: str, tokens: int) -> float:
        synthetic_prices = {
            "gpt-5.4": 0.000002,
            "gpt-5.4-mini": 0.0000008,
            "gpt-5.4-nano": 0.0000002,
        }
        return round(tokens * synthetic_prices.get(model, 0.000001), 8)

    def _hash(self, payload: dict[str, Any]) -> str:
        import hashlib

        return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()
