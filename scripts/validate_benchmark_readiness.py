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
from soa_benchmark.billing import (  # noqa: E402
    calculate_cost,
    load_live_pricing_snapshot,
    load_pricing_snapshot,
)
from soa_benchmark.providers import build_payload, load_provider_config  # noqa: E402
from soa_benchmark.runner import DEFAULT_PROVIDER_CONFIGS, preflight  # noqa: E402
from soa_benchmark.sandbox import load_sandbox_policy, scan_submission  # noqa: E402


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def verify_c4_fixture() -> None:
    fixture = json.loads((ROOT / "fixtures/codegen/c4/ae_small.json").read_text(encoding="utf-8"))
    expected = json.loads((ROOT / "fixtures/codegen/c4/expected_ae.json").read_text(encoding="utf-8"))
    if fixture.get("population_id") != "Total":
        raise AssertionError("C4 fixture population boundary is not explicit")
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
    schemas = {}
    for name in (
        "run_manifest.schema.json",
        "capability_probe.schema.json",
        "batch_manifest.schema.json",
        "pricing_snapshot.schema.json",
        "pricing_manifest.schema.json",
        "sandbox_policy.schema.json",
        "sandbox_evaluation_manifest.schema.json",
    ):
        schema = json.loads((ROOT / "benchmark_contracts" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        schemas[name] = schema
    expected_providers = {"openai", "anthropic", "kimi", "deepseek", "minimax"}
    provider_enums = {
        "capability probe": schemas["capability_probe.schema.json"]["properties"]["provider"]["properties"]["provider"]["enum"],
        "batch manifest": schemas["batch_manifest.schema.json"]["$defs"]["preflight"]["properties"]["providers"]["items"]["properties"]["provider"]["enum"],
        "pricing snapshot": schemas["pricing_snapshot.schema.json"]["properties"]["models"]["items"]["properties"]["provider"]["enum"],
    }
    for label, providers in provider_enums.items():
        if set(providers) != expected_providers:
            raise AssertionError(f"{label} provider enum differs from the approved matrix")
    registry_schema = schemas["pricing_manifest.schema.json"]
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


def verify_codegen_sandbox_contract() -> None:
    policy = load_sandbox_policy("configs/sandbox/codegen-c4-v1.json")
    if policy.data["configuration_state"] != "frozen":
        raise AssertionError("C4 sandbox policy must remain frozen after its image is pinned")
    isolation = policy.data["isolation"]
    if not isolation["image_reference"].endswith("@" + isolation["image_digest"]):
        raise AssertionError("C4 sandbox image reference is not digest-pinned")
    image_lock = (ROOT / "sandbox/codegen-c4/requirements.lock").read_text(
        encoding="utf-8"
    )
    if "polars==1.40.1" not in image_lock or "polars-runtime-32==1.40.1" not in image_lock:
        raise AssertionError("C4 sandbox image dependency lock is incomplete")
    lock_lines = (ROOT / "fixtures/codegen/c4/requirements.lock").read_text(
        encoding="utf-8"
    ).splitlines()
    if lock_lines != ["polars==1.40.1"] or version("polars") != "1.40.1":
        raise AssertionError("C4 Polars dependency differs from its model-visible lock")
    malicious = {
        "files": [
            {
                "path": "src/soa_experience/calculations/actual_to_expected.py",
                "content": "import socket\nopen('.env.local').read()\n",
            }
        ]
    }
    finding_codes = {item["code"] for item in scan_submission(malicious, policy)}
    if not {"forbidden_import", "forbidden_call", "forbidden_text_pattern"}.issubset(
        finding_codes
    ):
        raise AssertionError("sandbox static gate did not reject the adversarial fixture")
    benign = {
        "files": [
            {
                "path": "src/soa_experience/calculations/actual_to_expected.py",
                "content": (
                    "from __future__ import annotations\n"
                    "import hashlib\n"
                    "import json\n"
                    "import polars as pl\n"
                    "from decimal import Decimal\n"
                    "from soa_experience.contracts import ExperienceInput\n\n"
                    "def ratio(a, e):\n"
                    "    return None if not e else Decimal(a) / Decimal(e)\n"
                ),
            }
        ]
    }
    if scan_submission(benign, policy):
        raise AssertionError("sandbox static gate rejected the benign fixture")


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
    minimax = load_provider_config("configs/providers/minimax.json")
    minimax_payload = build_payload(minimax, prompt)
    if minimax_payload.get("thinking") != {"type": "disabled"}:
        raise AssertionError("MiniMax disabled thinking mapping is not explicit")
    if minimax_payload.get("service_tier") != "standard":
        raise AssertionError("MiniMax service tier is not fixed to standard")
    minimax_sensitivity = load_provider_config("configs/providers/minimax-thinking-64k.json")
    sensitivity_payload = build_payload(minimax_sensitivity, prompt)
    if sensitivity_payload.get("thinking") != {"type": "adaptive"}:
        raise AssertionError("MiniMax sensitivity thinking mapping is not adaptive")
    if sensitivity_payload.get("max_tokens") != 65536:
        raise AssertionError("MiniMax sensitivity output budget is not 64K")
    if "configs/providers/minimax-thinking-64k.json" in DEFAULT_PROVIDER_CONFIGS:
        raise AssertionError("MiniMax sensitivity lane entered the primary provider matrix")

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
    minimax_snapshot = load_live_pricing_snapshot(
        "configs/pricing/minimax-m3-standard-2026-08-07.json"
    )
    minimax_cost = calculate_cost(
        {
            "input_tokens": 2_000_000,
            "uncached_input_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
            "cache_write_input_tokens": 0,
            "output_tokens": 1_000_000,
            "reasoning_tokens": None,
            "total_tokens": 3_000_000,
            "integrity_valid": True,
            "integrity_failure_code": None,
        },
        minimax_snapshot,
        "minimax",
        "MiniMax-M3",
        "standard",
    )
    if minimax_cost["total_usd"] != "1.560000000000":
        raise AssertionError("MiniMax frozen price fixture failed")


def main() -> int:
    try:
        verify_c4_fixture()
        verify_contract_schema()
        verify_provider_and_cost_contracts()
        verify_dependency_lock()
        verify_codegen_sandbox_contract()
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
