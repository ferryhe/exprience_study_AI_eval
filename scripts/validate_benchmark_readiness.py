"""Offline verification for the direct-API benchmark execution baseline."""

from __future__ import annotations

from decimal import Decimal
from importlib.metadata import version
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soa_benchmark.canonical import render_prompt  # noqa: E402
from soa_benchmark.billing import calculate_cost, load_pricing_snapshot  # noqa: E402
from soa_benchmark.providers import build_payload, load_provider_config  # noqa: E402
from soa_benchmark.runner import DEFAULT_PROVIDER_CONFIGS, preflight  # noqa: E402


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def verify_c4_fixture() -> None:
    fixture = json.loads((ROOT / "fixtures/codegen/c4/ae_small.json").read_text(encoding="utf-8"))
    expected = json.loads((ROOT / "fixtures/codegen/c4/expected_ae.json").read_text(encoding="utf-8"))
    fields = (
        "Death_Count",
        "Death_Claim_Amount",
        "ExpDth_VBT2015_Cnt",
        "ExpDth_VBT2015_Amt",
        "ExpDth_VBT2015wMI_Cnt",
        "ExpDth_VBT2015wMI_Amt",
    )
    grouped: dict[str, dict[str, Decimal]] = {}
    for row in fixture["rows"]:
        target = grouped.setdefault(row["product"], {field: Decimal("0") for field in fields})
        for field in fields:
            target[field] += Decimal(row[field])
    term = grouped["Term"]
    term_expected = expected["expected_by_product"]["Term"]
    checks = {
        "actual_count": term["Death_Count"],
        "expected_count": term["ExpDth_VBT2015_Cnt"],
        "ae_count": term["Death_Count"] / term["ExpDth_VBT2015_Cnt"],
        "expected_count_with_mi": term["ExpDth_VBT2015wMI_Cnt"],
        "ae_count_with_mi": term["Death_Count"] / term["ExpDth_VBT2015wMI_Cnt"],
        "actual_amount": term["Death_Claim_Amount"],
        "expected_amount": term["ExpDth_VBT2015_Amt"],
        "ae_amount": term["Death_Claim_Amount"] / term["ExpDth_VBT2015_Amt"],
        "expected_amount_with_mi": term["ExpDth_VBT2015wMI_Amt"],
        "ae_amount_with_mi": term["Death_Claim_Amount"] / term["ExpDth_VBT2015wMI_Amt"],
    }
    for name, value in checks.items():
        if decimal_text(value) != term_expected[name]:
            raise AssertionError(f"C4 fixture mismatch for {name}")
    whole = grouped["Whole"]
    if whole["ExpDth_VBT2015_Cnt"] != 0 or expected["expected_by_product"]["Whole"]["ae_count"] is not None:
        raise AssertionError("C4 zero-denominator fixture is invalid")


def verify_contract_schema() -> None:
    for name in (
        "run_manifest.schema.json",
        "capability_probe.schema.json",
        "batch_manifest.schema.json",
        "pricing_snapshot.schema.json",
        "pricing_manifest.schema.json",
    ):
        schema = json.loads((ROOT / "benchmark_contracts" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    registry_schema = json.loads(
        (ROOT / "benchmark_contracts/pricing_manifest.schema.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (ROOT / "configs/pricing/pricing_manifest.json").read_text(encoding="utf-8")
    )
    errors = list(Draft202012Validator(registry_schema).iter_errors(registry))
    if errors:
        raise AssertionError("pricing manifest fixture violates its schema")


def verify_dependency_lock() -> None:
    locked = {}
    for line in (ROOT / "requirements-benchmark.lock").read_text(encoding="utf-8").splitlines():
        name, pinned = line.split("==", 1)
        locked[name] = pinned
    for name, pinned in locked.items():
        if version(name) != pinned:
            raise AssertionError(f"installed dependency differs from lock: {name}")


def verify_provider_and_cost_contracts() -> None:
    prompt = render_prompt("codegen-c4-v1", "fixtures/codegen/c4/input_manifest.json")
    deepseek = load_provider_config("configs/providers/deepseek.json")
    deepseek_payload = build_payload(deepseek, prompt)
    if deepseek_payload.get("thinking") != {"type": "enabled"}:
        raise AssertionError("DeepSeek thinking payload is not the documented object form")
    if deepseek_payload.get("reasoning_effort") != "high":
        raise AssertionError("DeepSeek reasoning effort was dropped")
    anthropic = load_provider_config("configs/providers/anthropic.json")
    if build_payload(anthropic, prompt).get("output_config") != {"effort": "high"}:
        raise AssertionError("Anthropic effort mapping is not explicit")

    snapshot = load_pricing_snapshot("fixtures/pricing/synthetic_pricing_snapshot.json")
    cost = calculate_cost(
        {
            "input_tokens": 6_000_000,
            "uncached_input_tokens": 1_000_000,
            "cache_read_input_tokens": 2_000_000,
            "cache_write_input_tokens": 3_000_000,
            "output_tokens": 500_000,
            "reasoning_tokens": 100_000,
            "total_tokens": 6_500_000,
            "integrity_valid": True,
            "integrity_failure_code": None,
        },
        snapshot,
        "openai",
        "synthetic-openai-model",
        "default",
    )
    if cost["total_usd"] != "10.500000000000":
        raise AssertionError("Decimal cost fixture failed")


def main() -> int:
    try:
        verify_c4_fixture()
        verify_contract_schema()
        verify_provider_and_cost_contracts()
        verify_dependency_lock()
        c4_prompt = render_prompt("codegen-c4-v1", "fixtures/codegen/c4/input_manifest.json")
        report_prompt = render_prompt("report-v1", "fixtures/report/small_evidence/input_manifest.json")
        for prompt in (c4_prompt, report_prompt):
            report = preflight(prompt, DEFAULT_PROVIDER_CONFIGS)
            hashes = {provider["model_visible_sha256"] for provider in report["providers"]}
            if hashes != {prompt.model_visible_sha256}:
                raise AssertionError("provider-visible hashes are not identical")
        if "evaluator_only" in c4_prompt.user:
            raise AssertionError("evaluator-only C4 expectation entered the model-visible prompt")
    except (AssertionError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: offline benchmark contracts and safety fixtures are internally consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
