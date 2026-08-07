from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scripts.repair_json_fence_run import RepairError, repair_json_fence_run  # noqa: E402
from soa_benchmark.billing import load_pricing_snapshot  # noqa: E402
from soa_benchmark.canonical import render_prompt, sha256  # noqa: E402
from soa_benchmark.providers import ProviderConfig, load_provider_config  # noqa: E402
from soa_benchmark.runner import run_once  # noqa: E402
from soa_benchmark.sandbox import evaluate_codegen  # noqa: E402


class JsonFenceRepairTests(unittest.TestCase):
    def _failed_run(
        self,
        root: Path,
        output_text: str,
        run_id: str,
        pack_id: str = "codegen-c4-v1",
        input_manifest: str = "fixtures/codegen/c4/input_manifest.json",
    ) -> Path:
        base = load_provider_config("configs/providers/openai.json")
        data = dict(base.data)
        data["requested_model_id"] = "synthetic-openai-model"
        data["effective_model_id"] = "synthetic-openai-model"
        config = ProviderConfig(base.path, data, base.sha256)
        response = json.dumps({
            "id": "response-id",
            "model": "synthetic-openai-model",
            "status": "completed",
            "output_text": output_text,
            "usage": {
                "input_tokens": 10,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens": 10,
                "total_tokens": 20,
            },
        }).encode("utf-8")
        identity = {
            "source_git_commit": None,
            "source_tree_dirty": True,
            "source_status_sha256": "1" * 64,
            "runner_source_sha256": "2" * 64,
        }
        with (
            patch("soa_benchmark.runner.load_provider_config", return_value=config),
            patch("soa_benchmark.runner._credential", return_value=("unused", "env_file")),
            patch(
                "soa_benchmark.runner._load_live_pricing",
                return_value=load_pricing_snapshot("fixtures/pricing/synthetic_pricing_snapshot.json"),
            ),
            patch("soa_benchmark.runner._source_identity", return_value=identity),
            patch(
                "soa_benchmark.runner._http_post",
                return_value=(200, {"x-request-id": "request-id"}, response, 1.0),
            ),
        ):
            return run_once(
                render_prompt(pack_id, input_manifest),
                "configs/providers/openai.json",
                ROOT / ".env.local",
                root,
                "fixtures/pricing/synthetic_pricing_snapshot.json",
                run_id,
            )

    @staticmethod
    def _submission() -> str:
        return json.dumps({
            "schema_version": "1.0.0",
            "task_id": "C4",
            "status": "completed",
            "summary": "synthetic",
            "files": [],
            "assumptions": [],
            "known_limitations": [],
            "evaluator_tests": [],
        }, separators=(",", ":"))

    @staticmethod
    def _report() -> str:
        section_ids = (
            "R01_EXECUTIVE_FINDINGS",
            "R02_DATA_VALIDATION",
            "R03_POPULATIONS_EXPECTED_BASIS",
            "R04_EXPOSURE_AND_TRENDS",
            "R05_PRODUCT_RESULTS",
            "R06_SEX_SMOKER_RISK_CLASS",
            "R07_AGE_AND_DURATION",
            "R08_MODEL_DIAGNOSTICS",
            "R09_PRACTICAL_IMPLICATIONS",
            "R10_LIMITATIONS_GOVERNANCE",
            "R11_REPRODUCIBILITY_REFERENCES",
        )
        paragraph = {"text": "Evidence-linked report paragraph.", "claim_ids": []}
        return json.dumps({
            "schema_version": "1.0.0",
            "report_title": "Synthetic experience study",
            "practitioner_summary": {"paragraphs": [paragraph]},
            "claims": [],
            "sections": [
                {"section_id": section_id, "title": section_id, "paragraphs": [paragraph]}
                for section_id in section_ids
            ],
            "limitations": [],
            "exhibit_index": [],
            "references": [],
            "unresolved_issues": [],
            "word_counts": {"main_report": 33, "practitioner_summary": 3},
        }, separators=(",", ":"))

    def test_exact_fence_creates_auditable_derived_run_without_parent_mutation(self) -> None:
        (ROOT / "runs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            root = Path(directory)
            parent = self._failed_run(root, f"```json\n{self._submission()}\n```", "parent")
            parent_manifest_before = parent.read_bytes()
            parent_record = json.loads(parent_manifest_before)
            parent_output = parent.parent / parent_record["extracted_output"]["path"]
            parent_output_before = parent_output.read_bytes()

            derived = repair_json_fence_run(parent, "repair", root / "repairs")

            self.assertEqual(parent.read_bytes(), parent_manifest_before)
            self.assertEqual(parent_output.read_bytes(), parent_output_before)
            derived_record = json.loads(derived.read_text(encoding="utf-8"))
            self.assertEqual(derived_record["status"], "response_contract_valid")
            self.assertTrue(derived_record["validation"]["response_schema_valid"])
            self.assertEqual(derived_record["cache_lane"], "sensitivity_outer_json_fence_repair")
            provenance = json.loads((derived.parent / "repair_provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["operation"]["internal_bytes_modified"], 0)
            self.assertEqual(provenance["parent"]["run_manifest_sha256"], sha256(parent_manifest_before))
            evaluation = evaluate_codegen(
                derived,
                "configs/sandbox/codegen-c4-v1.json",
                root / "evaluations",
                "repair-evaluation",
            )
            self.assertTrue(evaluation.is_file())

    def test_non_exact_fence_is_rejected(self) -> None:
        (ROOT / "runs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            root = Path(directory)
            parent = self._failed_run(root, f"```JSON\n{self._submission()}\n```", "parent")
            with self.assertRaisesRegex(RepairError, "exact single outer JSON fence"):
                repair_json_fence_run(parent, "repair", root / "repairs")
            self.assertFalse((root / "repairs" / "repair").exists())

    def test_report_without_top_level_status_creates_valid_derived_run(self) -> None:
        (ROOT / "runs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            root = Path(directory)
            parent = self._failed_run(
                root,
                f"```json\n{self._report()}\n```",
                "report-parent",
                "report-v1",
                "fixtures/report/small_evidence/input_manifest.json",
            )
            parent_before = parent.read_bytes()

            derived = repair_json_fence_run(parent, "report-repair", root / "repairs")

            self.assertEqual(parent.read_bytes(), parent_before)
            record = json.loads(derived.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "response_contract_valid")
            self.assertTrue(record["validation"]["response_schema_valid"])
            self.assertIsNone(record["validation"]["failure_code"])
            self.assertIsNone(record["validation"]["model_declared_status"])

    def test_invalid_json_and_schema_errors_are_not_repaired(self) -> None:
        (ROOT / "runs").mkdir(exist_ok=True)
        cases = ("{\"broken\":}", "{\"schema_version\":\"1.0.0\"}")
        for index, body in enumerate(cases):
            with self.subTest(body=body), tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
                root = Path(directory)
                parent = self._failed_run(root, f"```json\n{body}\n```", f"parent-{index}")
                with self.assertRaises(RepairError):
                    repair_json_fence_run(parent, "repair", root / "repairs")
                self.assertFalse((root / "repairs" / "repair").exists())


if __name__ == "__main__":
    unittest.main()
