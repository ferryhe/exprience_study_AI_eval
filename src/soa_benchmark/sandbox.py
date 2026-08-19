"""Static and digest-pinned Docker gates for code-generation submissions."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .canonical import (
    ROOT,
    ContractError,
    canonical_json_document,
    length_prefixed,
    read_bytes,
    read_text,
    sha256,
    validate_relative_path,
)
from .runner import (
    CODEGEN_OUTPUT_PATHS,
    _safe_write,
    _validate_document,
    _validate_model_json,
    canonical_json_bytes,
    ensure_safe_output_root,
    utc_now,
)
from .sandbox_docker import (
    DockerSandboxUnavailable,
    docker_backend_available,
    run_docker_evaluation,
)


SANDBOX_EVALUATOR_VERSION = "0.2.0"
EVALUATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
POLICY_ROOTS = ("configs/sandbox/",)


class SandboxError(RuntimeError):
    """Raised when a sandbox evaluation cannot be created safely."""


@dataclass(frozen=True)
class SandboxPolicy:
    path: str
    data: dict[str, Any]
    sha256: str


def load_sandbox_policy(relative_path: str) -> SandboxPolicy:
    """Load and validate a canonical public sandbox policy."""
    try:
        raw = read_bytes(relative_path, POLICY_ROOTS)
        data = json.loads(raw)
        schema = json.loads(read_text("benchmark_contracts/sandbox_policy.schema.json"))
    except (ContractError, json.JSONDecodeError) as exc:
        raise SandboxError("sandbox policy is not valid canonical JSON") from exc
    if not isinstance(data, dict):
        raise SandboxError("sandbox policy must be a JSON object")
    if raw != canonical_json_document(data):
        raise SandboxError("sandbox policy must use sorted-key canonical JSON formatting")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(data),
        key=lambda error: error.json_path,
    )
    if errors:
        raise SandboxError(f"sandbox policy violates contract at {errors[0].json_path}")
    isolation = data["isolation"]
    if data["configuration_state"] == "frozen":
        image_reference = isolation["image_reference"]
        image_digest = isolation["image_digest"]
        if image_reference is None or image_digest is None:
            raise SandboxError("frozen sandbox policy requires a digest-pinned image")
        if not image_reference.endswith("@" + image_digest):
            raise SandboxError("sandbox image reference must end with its declared digest")
    return SandboxPolicy(relative_path, data, sha256(raw))


def _runs_file(path: Path, expected_name: str | None = None) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    trusted = (ROOT / "runs").resolve(strict=False)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(trusted)
    except (OSError, ValueError) as exc:
        raise SandboxError("sandbox inputs must be files below runs/") from exc
    if expected_name is not None and resolved.name != expected_name:
        raise SandboxError(f"sandbox input must be named {expected_name}")
    if not resolved.is_file():
        raise SandboxError("sandbox input is not a regular file")
    current = ROOT
    try:
        parts = candidate.absolute().relative_to(ROOT).parts
    except ValueError as exc:
        raise SandboxError("sandbox input must remain inside the repository") from exc
    for part in parts:
        current = current / part
        is_junction = getattr(current, "is_junction", lambda: False)()
        if current.is_symlink() or is_junction:
            raise SandboxError("sandbox inputs must not traverse symlinks or junctions")
    return resolved


def _load_source_run(run_manifest_path: Path) -> tuple[dict[str, Any], bytes, Path, bytes]:
    path = _runs_file(run_manifest_path, "run_manifest.json")
    raw_manifest = path.read_bytes()
    try:
        manifest = json.loads(raw_manifest)
        schema = json.loads(read_text("benchmark_contracts/run_manifest.schema.json"))
    except (UnicodeDecodeError, json.JSONDecodeError, ContractError) as exc:
        raise SandboxError("run manifest is not valid JSON") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest),
        key=lambda error: error.json_path,
    )
    if errors:
        raise SandboxError(f"run manifest violates contract at {errors[0].json_path}")
    if manifest["status"] != "response_contract_valid":
        raise SandboxError("only response-contract-valid runs may enter sandbox evaluation")
    if manifest["validation"]["acceptance_scope"] != "transport_and_output_contract_only":
        raise SandboxError("run manifest has an unexpected acceptance scope")
    pack_id = manifest["prompt"]["pack_id"]
    if pack_id not in CODEGEN_OUTPUT_PATHS:
        raise SandboxError("sandbox evaluation accepts only code-generation packs")
    artifact = manifest["extracted_output"]
    if artifact["path"] is None or artifact["sha256"] is None or artifact["byte_length"] is None:
        raise SandboxError("run manifest has no extracted code submission")
    if artifact["path"] != "extracted_submission.json":
        raise SandboxError("codegen run must use the fixed extracted submission artifact name")
    try:
        relative_artifact = validate_relative_path(artifact["path"])
    except ContractError as exc:
        raise SandboxError("extracted submission path is unsafe") from exc
    submission_path = path.parent.joinpath(*relative_artifact.parts)
    try:
        resolved_submission = submission_path.resolve(strict=True)
        resolved_submission.relative_to(path.parent.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise SandboxError("extracted submission escapes its run directory") from exc
    if resolved_submission.is_symlink() or not resolved_submission.is_file():
        raise SandboxError("extracted submission must be a regular non-symlink file")
    submission_raw = resolved_submission.read_bytes()
    if sha256(submission_raw) != artifact["sha256"]:
        raise SandboxError("extracted submission hash mismatch")
    if len(submission_raw) != artifact["byte_length"]:
        raise SandboxError("extracted submission byte length mismatch")
    return manifest, raw_manifest, resolved_submission, submission_raw


def _finding(code: str, path: str, message: str, line: int | None = None) -> dict[str, Any]:
    return {"code": code, "path": path, "line": line, "message": message}


def scan_submission(submission: dict[str, Any], policy: SandboxPolicy) -> list[dict[str, Any]]:
    """Perform a deterministic, non-executing AST and text policy scan."""
    findings: list[dict[str, Any]] = []
    files = submission.get("files", [])
    if not files:
        findings.append(
            _finding("submission_no_files", "submission", "Submission contains no source files.")
        )
        return findings
    allowed_imports = set(policy.data["dependencies"]["allowed_import_roots"])
    scan = policy.data["static_scan"]
    forbidden_imports = set(scan["forbidden_import_roots"])
    forbidden_calls = set(scan["forbidden_calls"])
    allowed_suffixes = set(scan["allowed_suffixes"])
    forbidden_text = tuple(value.casefold() for value in scan["forbidden_text_patterns"])

    for item in sorted(files, key=lambda value: value["path"]):
        path = item["path"]
        content = item["content"]
        if PurePosixPath(path).suffix not in allowed_suffixes:
            findings.append(
                _finding("file_suffix_not_allowlisted", path, "Source file suffix is not allowlisted.")
            )
            continue
        folded = content.casefold()
        for pattern in forbidden_text:
            if pattern in folded:
                findings.append(
                    _finding(
                        "forbidden_text_pattern",
                        path,
                        "Source contains a forbidden security-sensitive text pattern.",
                    )
                )
        try:
            tree = ast.parse(content, filename=path)
        except SyntaxError as exc:
            findings.append(
                _finding("python_syntax_error", path, "Source is not valid Python syntax.", exc.lineno)
            )
            continue
        for node in ast.walk(tree):
            imports: list[str] = []
            if isinstance(node, ast.Import):
                imports = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports = [node.module.split(".", 1)[0]]
            for root in imports:
                if root in forbidden_imports:
                    findings.append(
                        _finding(
                            "forbidden_import",
                            path,
                            "Source imports a security-sensitive module.",
                            getattr(node, "lineno", None),
                        )
                    )
                elif root not in allowed_imports:
                    findings.append(
                        _finding(
                            "import_not_allowlisted",
                            path,
                            "Source imports a module outside the task allowlist.",
                            getattr(node, "lineno", None),
                        )
                    )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in forbidden_calls:
                    findings.append(
                        _finding(
                            "forbidden_call",
                            path,
                            "Source invokes a forbidden dynamic or I/O primitive.",
                            getattr(node, "lineno", None),
                        )
                    )
            if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                findings.append(
                    _finding(
                        "dunder_attribute_forbidden",
                        path,
                        "Source probes a forbidden dunder attribute.",
                        getattr(node, "lineno", None),
                    )
                )
    return sorted(
        findings,
        key=lambda item: (item["path"], item["line"] or 0, item["code"]),
    )


def _materialize(
    submission: dict[str, Any], evaluation_dir: Path
) -> tuple[str, int, int, str]:
    subject_root = evaluation_dir / "subject"
    subject_root.mkdir(parents=True, exist_ok=False)
    projection = bytearray(b"CODEGEN-SUBJECT/1\n")
    total_bytes = 0
    for item in sorted(submission["files"], key=lambda value: value["path"]):
        relative = validate_relative_path(item["path"])
        content = item["content"].encode("utf-8")
        destination = subject_root.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.resolve(strict=False).relative_to(subject_root.resolve(strict=True))
        except ValueError as exc:
            raise SandboxError("materialized source escapes the subject root") from exc
        if destination.exists():
            raise SandboxError("materialized source path is duplicated")
        _safe_write(destination, content)
        destination.chmod(0o444)
        projection.extend(length_prefixed("PATH", item["path"].encode("utf-8")))
        projection.extend(length_prefixed("CONTENT", content))
        total_bytes += len(content)
    relative_root = subject_root.relative_to(ROOT).as_posix()
    return relative_root, len(submission["files"]), total_bytes, sha256(bytes(projection))


def _test_gates(policy: SandboxPolicy) -> dict[str, Any]:
    gates = policy.data["test_gates"]
    return {
        "public": {"suite_id": gates["public_suite_id"], "status": "not_run"},
        "hidden_actuarial": {"suite_id": gates["hidden_suite_id"], "status": "not_run"},
        "hidden_protocol": gates["hidden_protocol"],
        "prompt_injection": {
            "suite_id": gates["prompt_injection_suite_id"],
            "status": "not_run",
        },
        "exfiltration": {"suite_id": gates["exfiltration_suite_id"], "status": "not_run"},
        "reproducibility": {
            "suite_id": f"deterministic-replay-{gates['deterministic_repetitions']}",
            "status": "not_run",
        },
    }


def _empty_execution(
    backend_available: bool,
    result: str,
    failure_code: str,
    limits: dict[str, Any],
) -> dict[str, Any]:
    return {
        "attempted": False,
        "backend_available": backend_available,
        "result": result,
        "failure_code": failure_code,
        "exit_code": None,
        "timed_out": False,
        "stdout_path": None,
        "stdout_sha256": None,
        "stderr_path": None,
        "stderr_sha256": None,
        "isolation_evidence": {
            "network_disabled": None,
            "read_only_root": None,
            "capabilities_dropped": None,
            "no_new_privileges": None,
            "non_root_user": None,
            "repository_not_mounted": None,
            "secrets_absent": None,
        },
        "limits": limits,
        "observed_resources": {
            "wall_clock_seconds": None,
            "cpu_seconds": None,
            "memory_peak_bytes": None,
            "disk_bytes": None,
            "pids_peak": None,
            "file_count": None,
            "output_bytes": None,
        },
    }


def evaluate_codegen(
    run_manifest_path: Path,
    sandbox_policy_path: str,
    output_root: Path,
    evaluation_id: str | None = None,
) -> Path:
    """Scan, materialize, and conditionally execute a code submission in Docker."""
    started_at = utc_now()
    manifest, raw_manifest, submission_path, submission_raw = _load_source_run(run_manifest_path)
    policy = load_sandbox_policy(sandbox_policy_path)
    pack_id = manifest["prompt"]["pack_id"]
    if pack_id not in policy.data["applies_to_pack_ids"]:
        raise SandboxError("sandbox policy does not apply to the source pack")
    try:
        submission_text = submission_raw.decode("utf-8")
        submission = json.loads(submission_text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SandboxError("extracted submission is not valid UTF-8 JSON") from exc
    if not isinstance(submission, dict):
        raise SandboxError("extracted submission must be a JSON object")
    schema_valid, failure = _validate_model_json(pack_id, submission_text)
    if not schema_valid:
        raise SandboxError(f"extracted submission no longer validates: {failure}")

    generated = evaluation_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-sandbox"
    if not EVALUATION_ID_PATTERN.fullmatch(generated):
        raise SandboxError("evaluation ID may contain only letters, numbers, dot, underscore, and hyphen")
    safe_root = ensure_safe_output_root(output_root)
    evaluation_dir = safe_root / generated
    if evaluation_dir.exists():
        raise SandboxError(f"sandbox evaluation directory already exists: {generated}")
    evaluation_dir.mkdir(parents=True, exist_ok=False)

    findings = scan_submission(submission, policy)
    if submission.get("status") != "completed":
        findings.append(
            _finding(
                "submission_not_completed",
                "submission",
                "Model-declared submission status is not completed.",
            )
        )
    limits = policy.data["resource_limits"]
    submitted_bytes = sum(
        len(item["content"].encode("utf-8")) for item in submission.get("files", [])
    )
    if len(submission.get("files", [])) > limits["file_count"]:
        findings.append(
            _finding(
                "file_count_limit_exceeded",
                "submission",
                "Submission exceeds the sandbox file-count limit.",
            )
        )
    if submitted_bytes > limits["disk_mb"] * 1024 * 1024:
        findings.append(
            _finding(
                "disk_limit_exceeded",
                "submission",
                "Submission exceeds the sandbox disk limit.",
            )
        )
    findings = sorted(
        findings,
        key=lambda item: (item["path"], item["line"] or 0, item["code"]),
    )

    materialization = {
        "status": "not_run",
        "root": None,
        "file_count": 0,
        "total_bytes": 0,
        "materialized_source_sha256": None,
    }
    backend_available = docker_backend_available()
    failure_codes: list[str]
    test_gates = _test_gates(policy)
    if findings:
        disposition = "failed"
        failure_codes = ["static_scan_failed"]
        execution = _empty_execution(
            backend_available,
            "not_run",
            "static_scan_failed",
            policy.data["resource_limits"],
        )
    else:
        root, file_count, total_bytes, source_hash = _materialize(submission, evaluation_dir)
        materialization = {
            "status": "completed",
            "root": root,
            "file_count": file_count,
            "total_bytes": total_bytes,
            "materialized_source_sha256": source_hash,
        }
        if policy.data["configuration_state"] != "frozen":
            block_code = "sandbox_policy_not_frozen"
            disposition = "blocked"
            failure_codes = [block_code]
            execution = _empty_execution(
                backend_available,
                "blocked",
                block_code,
                policy.data["resource_limits"],
            )
        elif not backend_available:
            block_code = "docker_backend_unavailable"
            disposition = "blocked"
            failure_codes = [block_code]
            execution = _empty_execution(
                backend_available,
                "blocked",
                block_code,
                policy.data["resource_limits"],
            )
        else:
            try:
                dynamic = run_docker_evaluation(
                    policy=policy.data,
                    subject_root=ROOT / root,
                    evaluation_id=generated,
                    source_file_count=file_count,
                    source_bytes=total_bytes,
                )
            except DockerSandboxUnavailable as exc:
                disposition = "blocked"
                failure_codes = [exc.code]
                execution = _empty_execution(
                    backend_available,
                    "blocked",
                    exc.code,
                    policy.data["resource_limits"],
                )
            else:
                stdout_path = evaluation_dir / "execution_stdout.json"
                stderr_path = evaluation_dir / "execution_stderr.txt"
                _safe_write(stdout_path, dynamic.stdout)
                _safe_write(stderr_path, dynamic.stderr)
                execution = dynamic.execution
                execution.update(
                    {
                        "stdout_path": stdout_path.relative_to(ROOT).as_posix(),
                        "stdout_sha256": sha256(dynamic.stdout),
                        "stderr_path": stderr_path.relative_to(ROOT).as_posix(),
                        "stderr_sha256": sha256(dynamic.stderr),
                    }
                )
                test_gates = dynamic.test_gates
                disposition = dynamic.machine_disposition
                failure_codes = dynamic.failure_codes

    isolation = policy.data["isolation"]
    source_relative = submission_path.relative_to(ROOT).as_posix()
    manifest_relative = _runs_file(run_manifest_path, "run_manifest.json").relative_to(ROOT).as_posix()
    record = {
        "schema_version": "1.0.0",
        "evaluation_id": generated,
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "source": {
            "run_manifest_path": manifest_relative,
            "run_manifest_sha256": sha256(raw_manifest),
            "run_id": manifest["run_id"],
            "pack_id": pack_id,
            "api_status": manifest["status"],
            "acceptance_scope": manifest["validation"]["acceptance_scope"],
            "extracted_submission_path": source_relative,
            "extracted_submission_sha256": sha256(submission_raw),
            "extracted_submission_bytes": len(submission_raw),
        },
        "policy": {
            "path": policy.path,
            "policy_id": policy.data["policy_id"],
            "sha256": policy.sha256,
            "configuration_state": policy.data["configuration_state"],
            "isolation_backend": isolation["backend"],
            "isolation_level": isolation["level"],
            "image_digest": isolation["image_digest"],
        },
        "static_scan": {
            "status": "failed" if findings else "passed",
            "scanned_file_count": len(submission["files"]),
            "findings": findings,
        },
        "materialization": materialization,
        "execution": execution,
        "test_gates": test_gates,
        "machine_disposition": disposition,
        "promotion_eligible": False,
        "failure_codes": failure_codes,
    }
    _validate_document(
        record,
        "benchmark_contracts/sandbox_evaluation_manifest.schema.json",
        "sandbox evaluation manifest",
    )
    output = evaluation_dir / "sandbox_evaluation_manifest.json"
    _safe_write(output, canonical_json_bytes(record))
    metadata = {
        "sandbox_evaluator_version": SANDBOX_EVALUATOR_VERSION,
        "sandbox_evaluation_manifest_sha256": sha256(output.read_bytes()),
    }
    _safe_write(evaluation_dir / "evaluator_metadata.json", canonical_json_bytes(metadata))
    return output
