from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soa_benchmark.billing import load_pricing_snapshot  # noqa: E402
from soa_benchmark.canonical import render_prompt  # noqa: E402
from soa_benchmark.providers import ProviderConfig, load_provider_config  # noqa: E402
from soa_benchmark.runner import run_once  # noqa: E402
from soa_benchmark.sandbox import (  # noqa: E402
    SandboxError,
    evaluate_codegen,
    load_sandbox_policy,
    scan_submission,
)


class CodegenSandboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_sandbox_policy("configs/sandbox/codegen-c4-v1.json")

    def _create_run(self, output_text: str, output_root: Path, run_id: str) -> Path:
        base = load_provider_config("configs/providers/openai.json")
        data = dict(base.data)
        data["requested_model_id"] = "synthetic-openai-model"
        data["effective_model_id"] = "synthetic-openai-model"
        config = ProviderConfig(base.path, data, base.sha256)
        response = json.dumps(
            {
                "id": "response-id",
                "model": "synthetic-openai-model",
                "status": "completed",
                "output_text": output_text,
                "usage": {
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                    "output_tokens": 40,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 140,
                },
            }
        ).encode("utf-8")
        identity = {
            "source_git_commit": None,
            "source_tree_dirty": True,
            "source_status_sha256": "1" * 64,
            "runner_source_sha256": "2" * 64,
        }
        prompt = render_prompt("codegen-c4-v1", "fixtures/codegen/c4/input_manifest.json")
        snapshot = load_pricing_snapshot("fixtures/pricing/synthetic_pricing_snapshot.json")
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
            return run_once(
                prompt,
                "configs/providers/openai.json",
                ROOT / ".env.local",
                output_root,
                "fixtures/pricing/synthetic_pricing_snapshot.json",
                run_id,
            )

    @staticmethod
    def _submission(content: str, status: str = "completed") -> str:
        return json.dumps(
            {
                "schema_version": "1.0.0",
                "task_id": "C4",
                "status": status,
                "summary": "synthetic",
                "files": [
                    {
                        "path": "src/soa_experience/calculations/actual_to_expected.py",
                        "content": content,
                    }
                ],
                "assumptions": [],
                "known_limitations": [],
                "evaluator_tests": [],
            }
        )

    def test_static_scan_rejects_network_subprocess_and_secret_reads(self) -> None:
        submission = json.loads(
            self._submission(
                "import socket\nimport subprocess\nopen('.env.local').read()\n"
            )
        )
        codes = {finding["code"] for finding in scan_submission(submission, self.policy)}
        self.assertIn("forbidden_import", codes)
        self.assertIn("forbidden_call", codes)
        self.assertIn("forbidden_text_pattern", codes)

    def test_static_scan_rejects_canary_emission(self) -> None:
        submission = json.loads(
            self._submission("LEAK = 'PROMPT_PACK_LEAKAGE_CANARY'\n")
        )
        codes = {finding["code"] for finding in scan_submission(submission, self.policy)}
        self.assertIn("forbidden_text_pattern", codes)

    def test_safe_submission_materializes_but_pre_freeze_policy_blocks_execution(self) -> None:
        (ROOT / "runs").mkdir(exist_ok=True)
        safe = self._submission(
            "from decimal import Decimal\n\ndef ratio(actual, expected):\n"
            "    return None if not expected else Decimal(actual) / Decimal(expected)\n"
        )
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            root = Path(directory)
            run_manifest = self._create_run(safe, root, "safe-source")
            evaluation = evaluate_codegen(
                run_manifest,
                "configs/sandbox/codegen-c4-v1.json",
                root / "evaluations",
                "safe-evaluation",
            )
            record = json.loads(evaluation.read_text(encoding="utf-8"))
            self.assertEqual(record["source"]["api_status"], "response_contract_valid")
            self.assertEqual(record["static_scan"]["status"], "passed")
            self.assertEqual(record["materialization"]["status"], "completed")
            self.assertFalse(record["execution"]["attempted"])
            self.assertEqual(record["machine_disposition"], "blocked")
            self.assertEqual(record["failure_codes"], ["sandbox_policy_not_frozen"])
            self.assertFalse(record["promotion_eligible"])
            subject = ROOT / record["materialization"]["root"]
            self.assertTrue(subject.is_dir())
            self.assertFalse((subject / ".env.local").exists())

    def test_malicious_submission_is_not_materialized(self) -> None:
        (ROOT / "runs").mkdir(exist_ok=True)
        malicious = self._submission(
            "import urllib.request\nopen('.env.local').read()\n"
        )
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            root = Path(directory)
            run_manifest = self._create_run(malicious, root, "malicious-source")
            source_record = json.loads(run_manifest.read_text(encoding="utf-8"))
            self.assertEqual(source_record["status"], "response_contract_valid")
            evaluation = evaluate_codegen(
                run_manifest,
                "configs/sandbox/codegen-c4-v1.json",
                root / "evaluations",
                "malicious-evaluation",
            )
            record = json.loads(evaluation.read_text(encoding="utf-8"))
            self.assertEqual(record["static_scan"]["status"], "failed")
            self.assertEqual(record["machine_disposition"], "failed")
            self.assertEqual(record["materialization"]["status"], "not_run")
            self.assertFalse((evaluation.parent / "subject").exists())

    def test_tampered_extracted_submission_is_rejected(self) -> None:
        (ROOT / "runs").mkdir(exist_ok=True)
        safe = self._submission("from decimal import Decimal\nVALUE = Decimal('1')\n")
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            root = Path(directory)
            run_manifest = self._create_run(safe, root, "tampered-source")
            record = json.loads(run_manifest.read_text(encoding="utf-8"))
            extracted = run_manifest.parent / record["extracted_output"]["path"]
            extracted.write_text(safe + "\n", encoding="utf-8")
            with self.assertRaisesRegex(SandboxError, "hash mismatch"):
                evaluate_codegen(
                    run_manifest,
                    "configs/sandbox/codegen-c4-v1.json",
                    root / "evaluations",
                    "tampered-evaluation",
                )


if __name__ == "__main__":
    unittest.main()
