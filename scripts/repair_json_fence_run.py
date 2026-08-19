"""Create an auditable sensitivity repair for one exact outer JSON Markdown fence.

Usage:
  python scripts/repair_json_fence_run.py \
    --parent-run-manifest runs/<run-id>/run_manifest.json \
    --repair-id <repair-id>

The parent run is never modified. The only permitted transformation is removing
the exact byte prefix `````json\n`` and suffix ``\n``` `` from its extracted
output. No JSON content or schema error is repaired.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soa_benchmark.canonical import read_text, sha256  # noqa: E402
from soa_benchmark.runner import (  # noqa: E402
    RUN_ID_PATTERN,
    _safe_write,
    _validate_model_json,
    canonical_json_bytes,
    ensure_safe_output_root,
    utc_now,
)


OPENING_FENCE = b"```json\n"
CLOSING_FENCE = b"\n```"
OPERATION = "remove_exact_single_outer_json_markdown_fence"


class RepairError(RuntimeError):
    """Raised when a run is not eligible for this narrow sensitivity repair."""


def _load_schema(relative_path: str) -> dict[str, Any]:
    try:
        schema = json.loads(read_text(relative_path))
        Draft202012Validator.check_schema(schema)
        return schema
    except (json.JSONDecodeError, OSError) as exc:
        raise RepairError(f"invalid schema: {relative_path}") from exc


def _schema_errors(value: Any, relative_path: str) -> list[Any]:
    return sorted(
        Draft202012Validator(
            _load_schema(relative_path), format_checker=FormatChecker()
        ).iter_errors(value),
        key=lambda error: error.json_path,
    )


def _runs_file(path: Path, expected_name: str) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to((ROOT / "runs").resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise RepairError("input must be an existing file below runs/") from exc
    if resolved.name != expected_name or resolved.is_symlink() or not resolved.is_file():
        raise RepairError(f"input must be a regular {expected_name} file")
    return resolved


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _parent_output(manifest_path: Path, manifest: dict[str, Any]) -> tuple[Path, bytes]:
    artifact = manifest["extracted_output"]
    relative = artifact.get("path")
    if not isinstance(relative, str) or Path(relative).name != relative:
        raise RepairError("parent extracted output path is not a simple filename")
    output_path = _runs_file(manifest_path.parent / relative, relative)
    raw = output_path.read_bytes()
    if artifact.get("sha256") != sha256(raw) or artifact.get("byte_length") != len(raw):
        raise RepairError("parent extracted output integrity check failed")
    return output_path, raw


def _remove_exact_outer_fence(raw: bytes) -> bytes:
    if not raw.startswith(OPENING_FENCE) or not raw.endswith(CLOSING_FENCE):
        raise RepairError("output is not wrapped in the exact single outer JSON fence")
    repaired = raw[len(OPENING_FENCE):-len(CLOSING_FENCE)]
    if not repaired:
        raise RepairError("outer JSON fence contains no content")
    return repaired


def repair_json_fence_run(
    parent_manifest_path: Path,
    repair_id: str,
    output_root: Path = ROOT / "runs" / "repairs",
) -> Path:
    """Derive a schema-valid run without changing the failed primary run."""
    if not RUN_ID_PATTERN.fullmatch(repair_id):
        raise RepairError("repair ID may contain only letters, numbers, dot, underscore, and hyphen")

    manifest_path = _runs_file(parent_manifest_path, "run_manifest.json")
    manifest_raw = manifest_path.read_bytes()
    try:
        parent = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepairError("parent run manifest is not valid JSON") from exc
    errors = _schema_errors(parent, "benchmark_contracts/run_manifest.schema.json")
    if errors:
        raise RepairError(f"parent run manifest violates contract at {errors[0].json_path}")
    if parent["status"] != "failed" or parent["validation"]["failure_code"] != "model_output_not_json":
        raise RepairError("parent run is not a model_output_not_json failure")

    parent_output_path, parent_output_raw = _parent_output(manifest_path, parent)
    repaired_raw = _remove_exact_outer_fence(parent_output_raw)
    try:
        repaired_text = repaired_raw.decode("utf-8")
        repaired_value = json.loads(repaired_text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepairError("fence removal did not produce valid UTF-8 JSON") from exc

    pack_id = parent["prompt"]["pack_id"]
    valid, failure_code = _validate_model_json(pack_id, repaired_text)
    if not valid:
        raise RepairError(f"fence removal did not satisfy the pack contract: {failure_code}")
    if pack_id == "report-v1":
        model_declared_status = None
    elif pack_id.startswith("codegen-"):
        model_declared_status = repaired_value["status"]
    else:
        raise RepairError(f"unsupported repair pack: {pack_id}")

    safe_output_root = ensure_safe_output_root(output_root)
    repair_dir = safe_output_root / repair_id
    if repair_dir.exists():
        raise RepairError(f"repair output already exists: {_relative(repair_dir)}")

    repaired_hash = sha256(repaired_raw)
    repaired_name = parent["extracted_output"]["path"]
    created_at = utc_now()
    derived = deepcopy(parent)
    derived["run_id"] = repair_id
    derived["status"] = "response_contract_valid"
    derived["completed_at_utc"] = created_at
    derived["cache_lane"] = "sensitivity_outer_json_fence_repair"
    derived["extracted_output"] = {
        "path": repaired_name,
        "sha256": repaired_hash,
        "byte_length": len(repaired_raw),
        "media_type": "application/json",
    }
    derived["validation"] = {
        "response_schema_valid": True,
        "failure_code": None,
        "model_output_sha256": repaired_hash,
        "acceptance_scope": "transport_and_output_contract_only",
        "model_declared_status": model_declared_status,
    }
    derived_errors = _schema_errors(derived, "benchmark_contracts/run_manifest.schema.json")
    if derived_errors:
        raise RepairError(f"derived run manifest violates contract at {derived_errors[0].json_path}")
    derived_raw = canonical_json_bytes(derived)

    provenance = {
        "schema_version": "1.0.0",
        "repair_id": repair_id,
        "repair_lane": "sensitivity",
        "created_at_utc": created_at,
        "parent": {
            "run_manifest_path": _relative(manifest_path),
            "run_manifest_sha256": sha256(manifest_raw),
            "extracted_output_path": _relative(parent_output_path),
            "extracted_output_sha256": sha256(parent_output_raw),
        },
        "operation": {
            "name": OPERATION,
            "removed_prefix_utf8": "```json\\n",
            "removed_suffix_utf8": "\\n```",
            "internal_bytes_modified": 0,
            "schema_repairs_applied": 0,
        },
        "repaired": {
            "extracted_output_path": f"runs/repairs/{repair_id}/{repaired_name}",
            "extracted_output_sha256": repaired_hash,
            "derived_run_manifest_path": f"runs/repairs/{repair_id}/run_manifest.json",
            "derived_run_manifest_sha256": sha256(derived_raw),
            "pack_id": pack_id,
            "pack_contract_valid": True,
        },
    }

    _safe_write(repair_dir / repaired_name, repaired_raw)
    _safe_write(repair_dir / "run_manifest.json", derived_raw)
    _safe_write(repair_dir / "repair_provenance.json", canonical_json_bytes(provenance))
    return repair_dir / "run_manifest.json"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--parent-run-manifest", required=True)
    result.add_argument("--repair-id", required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        output = repair_json_fence_run(Path(args.parent_run_manifest), args.repair_id)
    except RepairError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(_relative(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
