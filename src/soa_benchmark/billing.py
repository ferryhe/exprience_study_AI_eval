"""Versioned pricing snapshots and Decimal-only benchmark cost accounting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from .canonical import ContractError, read_text, sha256


TOKEN_RATE_FIELDS = {
    "uncached_input_tokens": "uncached_input_usd_per_million",
    "cache_read_input_tokens": "cache_read_input_usd_per_million",
    "cache_write_input_tokens": "cache_write_input_usd_per_million",
    "output_tokens": "output_usd_per_million",
}
OFFICIAL_PRICE_DOMAINS = {
    "openai": ("openai.com",),
    "anthropic": ("anthropic.com",),
    "kimi": ("moonshot.ai", "moonshot.cn"),
    "deepseek": ("deepseek.com",),
    "minimax": ("minimax.io", "minimaxi.com"),
}


class PricingError(ValueError):
    """Raised when a pricing snapshot is invalid or cannot price a live route."""


@dataclass(frozen=True)
class PricingSnapshot:
    path: str
    data: dict[str, Any]
    sha256: str

    @property
    def snapshot_id(self) -> str:
        return self.data["snapshot_id"]


def load_pricing_snapshot(relative_path: str) -> PricingSnapshot:
    try:
        text = read_text(relative_path)
        data = json.loads(text)
        schema = json.loads(read_text("benchmark_contracts/pricing_snapshot.schema.json"))
    except (ContractError, json.JSONDecodeError) as exc:
        raise PricingError(f"invalid pricing snapshot: {relative_path}") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data),
        key=str,
    )
    if errors:
        raise PricingError(f"pricing snapshot violates contract: {errors[0].json_path}")
    seen: set[tuple[str, str, str]] = set()
    for model in data["models"]:
        identity = (model["provider"], model["model_id"], model["service_tier"])
        if identity in seen:
            raise PricingError(f"duplicate pricing entry for {identity[0]}/{identity[1]}/{identity[2]}")
        seen.add(identity)
        for value in model["rates"].values():
            if value is not None:
                try:
                    if Decimal(value) < 0:
                        raise PricingError("pricing rates must be non-negative")
                except InvalidOperation as exc:
                    raise PricingError("pricing rates must be decimal strings") from exc
    return PricingSnapshot(relative_path, data, sha256(text.encode("utf-8")))


def load_live_pricing_snapshot(relative_path: str) -> PricingSnapshot:
    """Load only a hash-registered snapshot from configs/pricing/."""
    if (
        not relative_path.startswith("configs/pricing/")
        or relative_path == "configs/pricing/pricing_manifest.json"
    ):
        raise PricingError("live pricing snapshot must be registered under configs/pricing/")
    try:
        registry_text = read_text("configs/pricing/pricing_manifest.json")
        registry = json.loads(registry_text)
        registry_schema = json.loads(read_text("benchmark_contracts/pricing_manifest.schema.json"))
    except (ContractError, json.JSONDecodeError) as exc:
        raise PricingError("invalid live pricing registry") from exc
    errors = sorted(
        Draft202012Validator(registry_schema, format_checker=FormatChecker()).iter_errors(registry),
        key=str,
    )
    if errors:
        raise PricingError(f"live pricing registry violates contract: {errors[0].json_path}")
    matches = [item for item in registry["snapshots"] if item["path"] == relative_path]
    if len(matches) != 1:
        raise PricingError("live pricing snapshot is not uniquely registered")
    text = read_text(relative_path)
    encoded = text.encode("utf-8")
    if matches[0]["byte_length"] != len(encoded) or matches[0]["sha256"] != sha256(encoded):
        raise PricingError("live pricing snapshot integrity mismatch")
    snapshot = load_pricing_snapshot(relative_path)
    for model in snapshot.data["models"]:
        source = urlsplit(model["source_url"])
        hostname = (source.hostname or "").lower()
        if source.scheme != "https":
            raise PricingError(f"pricing source must use HTTPS: {model['provider']}")
        if not any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in OFFICIAL_PRICE_DOMAINS[model["provider"]]
        ):
            raise PricingError(f"pricing source is not an official provider domain: {model['provider']}")
    return snapshot


def find_price_entry(
    snapshot: PricingSnapshot, provider: str, model_id: str | None, service_tier: str
) -> dict[str, Any] | None:
    if model_id is None:
        return None
    matches = [
        item for item in snapshot.data["models"]
        if (
            item["provider"] == provider
            and item["model_id"] == model_id
            and item["service_tier"] == service_tier
        )
    ]
    if len(matches) > 1:
        raise PricingError(f"duplicate pricing entry for {provider}/{model_id}")
    return matches[0] if matches else None


def require_frozen_price(
    snapshot: PricingSnapshot,
    provider: str,
    effective_model_id: str | None,
    service_tier: str,
) -> None:
    if effective_model_id is None:
        raise PricingError("effective_model_not_frozen")
    if find_price_entry(snapshot, provider, effective_model_id, service_tier) is None:
        raise PricingError("effective_model_price_not_found")


def _money(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.000000000001"))
    return format(rounded, "f")


def unavailable_cost(
    reason_code: str,
    snapshot: PricingSnapshot | None = None,
    service_tier: str | None = None,
    known_subtotal_usd: str = "0.000000000000",
    incomplete_attempt_count: int = 1,
) -> dict[str, Any]:
    return {
        "currency": "USD",
        "complete": False,
        "pricing_snapshot_id": snapshot.snapshot_id if snapshot else None,
        "pricing_snapshot_sha256": snapshot.sha256 if snapshot else None,
        "model_id_priced": None,
        "service_tier_priced": service_tier,
        "components_usd": {
            "uncached_input": None,
            "cache_read_input": None,
            "cache_write_input": None,
            "output": None,
        },
        "total_usd": None,
        "known_subtotal_usd": known_subtotal_usd,
        "incomplete_attempt_count": incomplete_attempt_count,
        "reason_code": reason_code,
    }


def calculate_cost(
    usage: dict[str, Any],
    snapshot: PricingSnapshot | None,
    provider: str,
    model_id: str | None,
    service_tier: str,
) -> dict[str, Any]:
    """Calculate exact USD from mutually exclusive token buckets."""
    if snapshot is None:
        return unavailable_cost("price_snapshot_not_supplied", service_tier=service_tier)
    if model_id is None:
        return unavailable_cost("effective_model_not_available", snapshot, service_tier)
    entry = find_price_entry(snapshot, provider, model_id, service_tier)
    if entry is None:
        return unavailable_cost("model_price_not_found", snapshot, service_tier)
    if usage.get("integrity_valid") is not True:
        return unavailable_cost("usage_integrity_not_valid", snapshot, service_tier)
    if any(usage.get(field) is None for field in TOKEN_RATE_FIELDS):
        return unavailable_cost("usage_incomplete", snapshot, service_tier)

    values: dict[str, str] = {}
    total = Decimal("0")
    try:
        for token_field, rate_field in TOKEN_RATE_FIELDS.items():
            tokens = usage[token_field]
            assert tokens is not None
            rate_text = entry["rates"][rate_field]
            if rate_text is None and tokens > 0:
                return unavailable_cost("price_component_missing", snapshot, service_tier)
            amount = Decimal(tokens) * Decimal(rate_text or "0") / Decimal("1000000")
            component = token_field.removesuffix("_tokens")
            values[component] = _money(amount)
            total += amount
    except (InvalidOperation, OverflowError):
        return unavailable_cost("cost_arithmetic_error", snapshot, service_tier)
    return {
        "currency": "USD",
        "complete": True,
        "pricing_snapshot_id": snapshot.snapshot_id,
        "pricing_snapshot_sha256": snapshot.sha256,
        "model_id_priced": model_id,
        "service_tier_priced": service_tier,
        "components_usd": values,
        "total_usd": _money(total),
        "known_subtotal_usd": _money(total),
        "incomplete_attempt_count": 0,
        "reason_code": "calculated_from_frozen_snapshot",
    }


def sum_attempt_costs(
    costs: list[dict[str, Any]],
    snapshot: PricingSnapshot | None,
    model_id: str | None,
    service_tier: str,
) -> dict[str, Any]:
    """Sum known per-attempt charges without treating unavailable telemetry as zero."""
    if not costs:
        return unavailable_cost("no_attempt_costs", snapshot, service_tier)
    if any(not item["complete"] for item in costs):
        reason = "price_snapshot_not_supplied" if snapshot is None else "one_or_more_attempt_costs_incomplete"
        known = sum(
            (Decimal(item["known_subtotal_usd"]) for item in costs),
            Decimal("0"),
        )
        return unavailable_cost(
            reason,
            snapshot,
            service_tier,
            _money(known),
            sum(not item["complete"] for item in costs),
        )
    components = {name: Decimal("0") for name in ("uncached_input", "cache_read_input", "cache_write_input", "output")}
    for item in costs:
        for name in components:
            components[name] += Decimal(item["components_usd"][name])
    total = sum(components.values(), Decimal("0"))
    return {
        "currency": "USD",
        "complete": True,
        "pricing_snapshot_id": snapshot.snapshot_id if snapshot else None,
        "pricing_snapshot_sha256": snapshot.sha256 if snapshot else None,
        "model_id_priced": model_id,
        "service_tier_priced": service_tier,
        "components_usd": {name: _money(value) for name, value in components.items()},
        "total_usd": _money(total),
        "known_subtotal_usd": _money(total),
        "incomplete_attempt_count": 0,
        "reason_code": "sum_of_all_attempt_costs",
    }
