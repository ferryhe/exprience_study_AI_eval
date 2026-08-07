from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soa_benchmark.billing import (  # noqa: E402
    PricingError,
    calculate_cost,
    load_live_pricing_snapshot,
    load_pricing_snapshot,
)
from soa_benchmark.canonical import (  # noqa: E402
    ContractError,
    _load_pack,
    _validate_input_manifest_contract,
    _validate_model_visible_artifact,
    render_prompt,
    validate_approved_artifact_path,
    validate_relative_path,
)
from soa_benchmark.providers import (  # noqa: E402
    ProviderError,
    ProviderConfig,
    build_payload,
    load_provider_config,
    normalize_usage,
)
from soa_benchmark.runner import (  # noqa: E402
    RunnerError,
    NoRedirectHandler,
    PROBE_MAX_OUTPUT_TOKENS,
    TransportFailure,
    _execute_request,
    _account_attempts,
    _read_response,
    _response_has_raw_reasoning,
    _retry_after_seconds,
    _validate_model_json,
    _source_identity,
    capability_probe,
    classify_transport_error,
    ensure_safe_output_root,
    load_env_file,
    run_once,
    run_matrix,
    validate_probe_output,
)
from scripts.validate_prompt_library import validate_provider_state  # noqa: E402


class CanonicalInputTests(unittest.TestCase):
    def test_hidden_and_secret_paths_are_rejected(self) -> None:
        for value in (".env.local", "fixtures/codegen/.secret", "data/raw.tsv", "../secret"):
            with self.subTest(value=value), self.assertRaises(ContractError):
                validate_relative_path(value)

    def test_artifact_roots_are_hard_allowlisted(self) -> None:
        validate_approved_artifact_path("codegen", "fixtures/codegen/c4/ae_small.json")
        validate_approved_artifact_path("report", "fixtures/report/small_evidence/overview.csv")
        with self.assertRaises(ContractError):
            validate_approved_artifact_path("codegen", "configs/providers/openai.json")
        with self.assertRaises(ContractError):
            validate_approved_artifact_path(
                "codegen", "fixtures/codegen/c4/expected_ae.json", "codegen-c4-v1"
            )

    def test_pack_type_must_match_pack_id(self) -> None:
        manifest = {
            "schema_version": "1.0.0",
            "pack_id": "codegen-c4-v1",
            "pack_type": "report",
            "artifacts": [],
            "forbidden_roots": [],
        }
        with self.assertRaises(ContractError):
            _validate_input_manifest_contract(manifest, "codegen-c4-v1", "codegen", "fixture")

    def test_model_visible_json_must_be_canonical(self) -> None:
        artifact = {"path": "fixtures/codegen/c4/test.json", "media_type": "application/json"}
        with self.assertRaises(ContractError):
            _validate_model_visible_artifact(artifact, b'{"b": 1, "a": 2}\n')

    def test_registered_fixtures_render(self) -> None:
        codegen = render_prompt("codegen-c4-v1", "fixtures/codegen/c4/input_manifest.json")
        report = render_prompt("report-v1", "fixtures/report/small_evidence/input_manifest.json")
        self.assertNotIn("evaluator_only", codegen.user)
        self.assertNotEqual(codegen.model_visible_sha256, report.model_visible_sha256)

    def test_prompt_manifest_cannot_add_gold_component(self) -> None:
        manifest = json.loads((ROOT / "prompts/prompt_manifest.json").read_text(encoding="utf-8"))
        pack = next(item for item in manifest["packs"] if item["pack_id"] == "codegen-c4-v1")
        pack["components"].append({
            "role": "user",
            "path": "fixtures/codegen/c4/expected_ae.json",
        })
        with patch("soa_benchmark.canonical.load_json", return_value=manifest):
            with self.assertRaises(ContractError):
                _load_pack("codegen-c4-v1")


class ProviderContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prompt = render_prompt("codegen-c4-v1", "fixtures/codegen/c4/input_manifest.json")

    def test_deepseek_thinking_payload_is_exact(self) -> None:
        config = load_provider_config("configs/providers/deepseek.json")
        payload = build_payload(config, self.prompt)
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertNotIn("effort", payload)

    def test_anthropic_effort_is_explicit(self) -> None:
        config = load_provider_config("configs/providers/anthropic.json")
        payload = build_payload(config, self.prompt)
        self.assertEqual(payload["output_config"], {"effort": "high"})

    def test_provider_base_url_cannot_redirect_a_key(self) -> None:
        original = json.loads((ROOT / "configs/providers/openai.json").read_text(encoding="utf-8"))
        original["base_url"] = "https://attacker.invalid"
        malicious = json.dumps(original) + "\n"
        manifest = json.loads((ROOT / "prompts/prompt_manifest.json").read_text(encoding="utf-8"))
        registration = next(
            item for item in manifest["artifacts"] if item["path"] == "configs/providers/openai.json"
        )
        registration["byte_length"] = len(malicious.encode("utf-8"))
        registration["sha256"] = hashlib.sha256(malicious.encode("utf-8")).hexdigest()

        def fake_read(path: str) -> str:
            return json.dumps(manifest) if path == "prompts/prompt_manifest.json" else malicious

        with patch("soa_benchmark.providers.read_text", side_effect=fake_read):
            with self.assertRaises(ProviderError):
                load_provider_config("configs/providers/openai.json")

    def test_frozen_provider_state_is_validator_reachable(self) -> None:
        config = json.loads((ROOT / "configs/providers/openai.json").read_text(encoding="utf-8"))
        config.update({
            "configuration_state": "frozen",
            "effective_model_id": "verified-model-id",
            "effective_model_reason_code": "capability_probe_confirmed",
            "version_semantics": "pinned_exact",
            "capability_probe_date": "2026-08-06",
        })
        validate_provider_state(config)

    def test_openai_usage_includes_cache_and_reasoning(self) -> None:
        config = load_provider_config("configs/providers/openai.json")
        usage = normalize_usage(config, {
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 10},
                "output_tokens": 40,
                "output_tokens_details": {"reasoning_tokens": 15},
                "total_tokens": 140,
            }
        })
        self.assertEqual(usage, {
            "input_tokens": 100,
            "uncached_input_tokens": 70,
            "cache_read_input_tokens": 20,
            "cache_write_input_tokens": 10,
            "output_tokens": 40,
            "reasoning_tokens": 15,
            "total_tokens": 140,
            "integrity_valid": True,
            "integrity_failure_code": None,
        })

    def test_openai_service_tier_is_fixed(self) -> None:
        config = load_provider_config("configs/providers/openai.json")
        self.assertEqual(build_payload(config, self.prompt)["service_tier"], "default")

    def test_deepseek_cache_usage_uses_documented_fields(self) -> None:
        config = load_provider_config("configs/providers/deepseek.json")
        usage = normalize_usage(config, {
            "usage": {
                "prompt_tokens": 100,
                "prompt_cache_hit_tokens": 30,
                "prompt_cache_miss_tokens": 70,
                "completion_tokens": 20,
                "completion_tokens_details": {"reasoning_tokens": 8},
                "total_tokens": 120,
            }
        })
        self.assertEqual(usage["cache_read_input_tokens"], 30)
        self.assertEqual(usage["uncached_input_tokens"], 70)
        self.assertEqual(usage["reasoning_tokens"], 8)


class BillingAndRunnerTests(unittest.TestCase):
    def test_decimal_cost_calculation(self) -> None:
        snapshot = load_pricing_snapshot("fixtures/pricing/synthetic_pricing_snapshot.json")
        usage = {
            "input_tokens": 6_000_000,
            "uncached_input_tokens": 1_000_000,
            "cache_read_input_tokens": 2_000_000,
            "cache_write_input_tokens": 3_000_000,
            "output_tokens": 500_000,
            "reasoning_tokens": 100_000,
            "total_tokens": 6_500_000,
            "integrity_valid": True,
            "integrity_failure_code": None,
        }
        cost = calculate_cost(usage, snapshot, "openai", "synthetic-openai-model", "default")
        self.assertTrue(cost["complete"])
        self.assertEqual(cost["total_usd"], "10.500000000000")

    def test_inconsistent_usage_cannot_produce_complete_cost(self) -> None:
        config = load_provider_config("configs/providers/openai.json")
        usage = normalize_usage(config, {
            "usage": {
                "input_tokens": 10,
                "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 30},
                "output_tokens": 5,
                "total_tokens": 15,
            }
        })
        snapshot = load_pricing_snapshot("fixtures/pricing/synthetic_pricing_snapshot.json")
        cost = calculate_cost(usage, snapshot, "openai", "synthetic-openai-model", "default")
        self.assertFalse(usage["integrity_valid"])
        self.assertFalse(cost["complete"])

    def test_retry_usage_remains_incomplete_with_known_subtotal(self) -> None:
        config = load_provider_config("configs/providers/openai.json")
        snapshot = load_pricing_snapshot("fixtures/pricing/synthetic_pricing_snapshot.json")
        response = {
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 10},
                "output_tokens": 40,
                "total_tokens": 140,
            }
        }
        attempts = [{}, {}]
        usage, summary, cost = _account_attempts(
            config, attempts, [None, response], snapshot, "synthetic-openai-model"
        )
        self.assertIsNone(usage["input_tokens"])
        self.assertEqual(summary["known_token_subtotals"]["input_tokens"], 100)
        self.assertEqual(summary["missing_attempt_counts"]["input_tokens"], 1)
        self.assertFalse(cost["complete"])
        self.assertNotEqual(cost["known_subtotal_usd"], "0.000000000000")

    def test_synthetic_price_snapshot_is_blocked_for_live_runs(self) -> None:
        with self.assertRaises(PricingError):
            load_live_pricing_snapshot("fixtures/pricing/synthetic_pricing_snapshot.json")

    def test_env_file_overrides_process_environment_without_exposing_value(self) -> None:
        (ROOT / "runs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            env_path = Path(directory) / "test.env"
            env_path.write_text("OPENAI_API_KEY=file-value\n", encoding="utf-8", newline="\n")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "process-value"}):
                values, file_names = load_env_file(env_path)
            self.assertEqual(values["OPENAI_API_KEY"], "file-value")
            self.assertEqual(file_names, {"OPENAI_API_KEY"})

    def test_output_root_is_confined_to_runs(self) -> None:
        self.assertEqual(ensure_safe_output_root(ROOT / "runs"), (ROOT / "runs").resolve())
        with self.assertRaises(RunnerError):
            ensure_safe_output_root(ROOT / "outputs")

    def test_transport_error_classification_is_allowlist_friendly(self) -> None:
        self.assertEqual(classify_transport_error(URLError(TimeoutError())), "timeout")
        self.assertEqual(classify_transport_error(URLError(PermissionError())), "network_other")

    def test_redirects_are_never_followed_with_credentials(self) -> None:
        self.assertIsNone(
            NoRedirectHandler().redirect_request(
                None, None, 302, "Found", {}, "https://attacker.invalid/collect"
            )
        )

    def test_retry_after_zero_is_respected(self) -> None:
        self.assertEqual(_retry_after_seconds({"Retry-After": "0"}), 0.0)

    def test_response_read_honors_expired_deadline(self) -> None:
        with self.assertRaises(TransportFailure):
            _read_response(None, 0.0)

    def test_attempt_ledger_persists_every_http_response(self) -> None:
        config = load_provider_config("configs/providers/openai.json")
        (ROOT / "runs").mkdir(exist_ok=True)
        responses = [
            (429, {"Retry-After": "0.001", "x-request-id": "first"}, b'{"error":"rate"}', 2.0),
            (200, {"x-request-id": "second"}, b'{"id":"r","output_text":"{}"}', 3.0),
        ]
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            root = Path(directory)
            run_dir = root / "ledger"
            run_dir.mkdir()
            with patch("soa_benchmark.runner._http_post", side_effect=responses), patch("soa_benchmark.runner.time.sleep"):
                result = _execute_request(config, {"test": True}, "unused", run_dir, root)
            self.assertEqual(len(result["attempts"]), 2)
            self.assertTrue(result["attempts"][0]["retryable"])
            self.assertEqual(result["attempts"][0]["request_id"], "first")
            self.assertIsNotNone(result["attempts"][0]["raw_response_sha256"])
            self.assertIsNotNone(result["attempts"][1]["raw_response_sha256"])

    def test_source_identity_records_dirty_state_and_hashes(self) -> None:
        identity = _source_identity()
        self.assertIsInstance(identity["source_tree_dirty"], bool)
        self.assertRegex(identity["source_status_sha256"], r"^[a-f0-9]{64}$")
        self.assertRegex(identity["runner_source_sha256"], r"^[a-f0-9]{64}$")

    def test_probe_requires_exact_json(self) -> None:
        self.assertEqual(validate_probe_output('{"ok":true}'), (True, None))
        self.assertFalse(validate_probe_output('{"ok":true,"extra":1}')[0])
        self.assertFalse(validate_probe_output("ok")[0])

    def test_codegen_task_and_paths_require_semantic_match(self) -> None:
        base = {
            "schema_version": "1.0.0",
            "task_id": "C1",
            "status": "completed",
            "summary": "synthetic",
            "files": [],
            "assumptions": [],
            "known_limitations": [],
            "evaluator_tests": [],
        }
        self.assertEqual(
            _validate_model_json("codegen-c4-v1", json.dumps(base))[1],
            "codegen_task_id_mismatch",
        )
        base["task_id"] = "C4"
        base["files"] = [{"path": "src/../../.env.local", "content": "x"}]
        self.assertEqual(
            _validate_model_json("codegen-c4-v1", json.dumps(base))[1],
            "codegen_file_path_unsafe",
        )

    def test_raw_reasoning_detection_is_provider_specific(self) -> None:
        openai = load_provider_config("configs/providers/openai.json")
        deepseek = load_provider_config("configs/providers/deepseek.json")
        self.assertFalse(_response_has_raw_reasoning(openai, {"reasoning": {"effort": "high"}}))
        self.assertTrue(_response_has_raw_reasoning(deepseek, {
            "choices": [{"message": {"reasoning_content": "retained reasoning"}}]
        }))

    def test_matrix_requires_position_balanced_repetitions(self) -> None:
        prompt = render_prompt("codegen-c4-v1", "fixtures/codegen/c4/input_manifest.json")
        with self.assertRaises(RunnerError):
            run_matrix(
                prompt,
                (
                    "configs/providers/openai.json",
                    "configs/providers/anthropic.json",
                    "configs/providers/kimi.json",
                    "configs/providers/deepseek.json",
                ),
                ROOT / ".env.local",
                ROOT / "runs",
                "configs/pricing/not-registered.json",
                1,
            )

    def test_transport_failed_probe_still_writes_record(self) -> None:
        (ROOT / "runs").mkdir(exist_ok=True)
        identity = {
            "source_git_commit": None,
            "source_tree_dirty": True,
            "source_status_sha256": "1" * 64,
            "runner_source_sha256": "2" * 64,
        }
        seen_payloads: list[dict[str, object]] = []

        def transport_failure(config: object, payload: dict[str, object], key: str, deadline: float) -> None:
            seen_payloads.append(payload)
            raise TransportFailure("timeout")

        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            with (
                patch("soa_benchmark.runner._credential", return_value=("unused", "env_file")),
                patch("soa_benchmark.runner._source_identity", return_value=identity),
                patch("soa_benchmark.runner._http_post", side_effect=transport_failure),
                patch("soa_benchmark.runner.time.sleep"),
            ):
                output = capability_probe(
                    "configs/providers/openai.json", ROOT / ".env.local", Path(directory), "offline-probe"
                )
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "transport_failed")
            self.assertEqual(len(record["attempts"]), 3)
            self.assertIn("usage", record["attempts"][0])
            self.assertIn("cost", record["attempts"][0])
            self.assertTrue(seen_payloads)
            self.assertEqual(seen_payloads[0]["max_output_tokens"], PROBE_MAX_OUTPUT_TOKENS)

    def test_mocked_paid_run_writes_schema_valid_attempt_accounting(self) -> None:
        base = load_provider_config("configs/providers/openai.json")
        data = dict(base.data)
        data["requested_model_id"] = "synthetic-openai-model"
        data["effective_model_id"] = "synthetic-openai-model"
        config = ProviderConfig(base.path, data, base.sha256)
        output_text = json.dumps({
            "schema_version": "1.0.0",
            "task_id": "C4",
            "status": "completed",
            "summary": "synthetic",
            "files": [],
            "assumptions": [],
            "known_limitations": [],
            "evaluator_tests": [],
        })
        response = json.dumps({
            "id": "response-id",
            "model": "synthetic-openai-model",
            "status": "completed",
            "output_text": output_text,
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 10},
                "output_tokens": 40,
                "output_tokens_details": {"reasoning_tokens": 5},
                "total_tokens": 140,
            },
        }).encode("utf-8")
        identity = {
            "source_git_commit": None,
            "source_tree_dirty": True,
            "source_status_sha256": "1" * 64,
            "runner_source_sha256": "2" * 64,
        }
        prompt = render_prompt("codegen-c4-v1", "fixtures/codegen/c4/input_manifest.json")
        snapshot = load_pricing_snapshot("fixtures/pricing/synthetic_pricing_snapshot.json")
        (ROOT / "runs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            with (
                patch("soa_benchmark.runner.load_provider_config", return_value=config),
                patch("soa_benchmark.runner._credential", return_value=("unused", "env_file")),
                patch("soa_benchmark.runner._load_live_pricing", return_value=snapshot),
                patch("soa_benchmark.runner._source_identity", return_value=identity),
                patch(
                    "soa_benchmark.runner._http_post",
                    return_value=(200, {"x-request-id": "request-id"}, response, 5.0),
                ),
            ):
                output = run_once(
                    prompt,
                    "configs/providers/openai.json",
                    ROOT / ".env.local",
                    Path(directory),
                    "fixtures/pricing/synthetic_pricing_snapshot.json",
                    "offline-run",
                )
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "response_contract_valid")
            self.assertEqual(
                record["validation"]["acceptance_scope"],
                "transport_and_output_contract_only",
            )
            self.assertEqual(record["validation"]["model_declared_status"], "completed")
            extracted = output.parent / record["extracted_output"]["path"]
            self.assertEqual(extracted.read_text(encoding="utf-8"), output_text)
            self.assertEqual(record["extracted_output"]["byte_length"], len(output_text))
            self.assertTrue(record["cost"]["complete"])
            self.assertEqual(record["attempts"][0]["usage"]["reasoning_tokens"], 5)


if __name__ == "__main__":
    unittest.main()
