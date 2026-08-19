"""Unified direct-API runner with replayable, secret-free run records."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead, RemoteDisconnected
import json
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import re
import socket
import subprocess
import time
from typing import Any
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from jsonschema import Draft202012Validator, FormatChecker

from .billing import (
    PricingError,
    PricingSnapshot,
    calculate_cost,
    load_live_pricing_snapshot,
    require_frozen_price,
    sum_attempt_costs,
)
from .canonical import (
    ROOT,
    ContractError,
    RenderedPrompt,
    length_prefixed,
    read_text,
    sha256,
    validate_relative_path,
)
from .providers import (
    ProviderConfig,
    ProviderError,
    build_payload,
    endpoint_url,
    extract_text,
    load_provider_config,
    model_visible_hash_from_payload,
    normalize_usage,
    request_headers,
    returned_model_id,
    returned_service_tier,
)


RUNNER_VERSION = "0.3.0"
PROBE_MAX_OUTPUT_TOKENS = 64
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
DEFAULT_PROVIDER_CONFIGS = (
    "configs/providers/openai.json",
    "configs/providers/anthropic.json",
    "configs/providers/kimi.json",
    "configs/providers/deepseek.json",
    "configs/providers/minimax.json",
)
TOKEN_FIELDS = (
    "input_tokens",
    "uncached_input_tokens",
    "cache_read_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
)
EMPTY_USAGE: dict[str, Any] = {
    **{field: None for field in TOKEN_FIELDS},
    "integrity_valid": False,
    "integrity_failure_code": "usage_missing",
}
CODEGEN_OUTPUT_PATHS = {
    "codegen-c1-v1": {
        "src/soa_experience/sources/manifest.py",
        "src/soa_experience/data/schema.py",
        "src/soa_experience/data/ingest.py",
    },
    "codegen-c2-v1": {
        "src/soa_experience/validation/models.py",
        "src/soa_experience/validation/rules.py",
        "src/soa_experience/validation/runner.py",
    },
    "codegen-c3-v1": {
        "src/soa_experience/populations/definitions.py",
        "src/soa_experience/populations/apply.py",
    },
    "codegen-c4-v1": {
        "src/soa_experience/calculations/actual_to_expected.py",
        "src/soa_experience/calculations/uncertainty.py",
    },
    "codegen-c5-v1": {
        "src/soa_experience/exhibits/definitions.py",
        "src/soa_experience/exhibits/build.py",
        "src/soa_experience/evidence/identifiers.py",
    },
    "codegen-c6-v1": {
        "src/soa_experience/models/poisson_glm.py",
        "src/soa_experience/models/diagnostics.py",
    },
    "codegen-c7-v1": {
        "src/soa_experience/evidence/models.py",
        "src/soa_experience/evidence/build.py",
        "src/soa_experience/evidence/validate.py",
    },
}


class RunnerError(RuntimeError):
    """Raised when a live benchmark run cannot be started safely."""


class TransportFailure(RuntimeError):
    """A normalized transport failure with a stable retry classification."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class NoRedirectHandler(HTTPRedirectHandler):
    """Prevent credential-bearing requests from following any redirect."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _safe_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def ensure_safe_output_root(output_root: Path) -> Path:
    """Allow retained provider data only below the Git-ignored repository runs root."""
    candidate = output_root if output_root.is_absolute() else ROOT / output_root
    trusted = (ROOT / "runs").resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(trusted)
    except ValueError as exc:
        raise RunnerError("output root must be runs/ or one of its descendants") from exc
    lexical = candidate.absolute()
    current = ROOT
    try:
        parts = lexical.relative_to(ROOT).parts
    except ValueError as exc:
        raise RunnerError("output root must be inside the repository") from exc
    for part in parts:
        current = current / part
        is_junction = getattr(current, "is_junction", lambda: False)()
        if current.exists() and (current.is_symlink() or is_junction):
            raise RunnerError("output root must not traverse a symlink or junction")
    return resolved


def load_env_file(env_file: Path) -> tuple[dict[str, str], set[str]]:
    """Load KEY=VALUE credentials; the project file explicitly overrides process values."""
    values = dict(os.environ)
    file_names: set[str] = set()
    if not env_file.exists():
        return values, file_names
    if env_file.is_symlink():
        raise RunnerError("credential file must not be a symlink")
    try:
        content = env_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RunnerError("credential file is not readable UTF-8") from exc
    if content.startswith("\ufeff"):
        raise RunnerError("credential file must not contain a BOM")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise RunnerError("credential file contains a malformed line")
        name, value = stripped.split("=", 1)
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
            raise RunnerError("credential file contains an invalid variable name")
        values[name] = value
        file_names.add(name)
    return values, file_names


def _credential(config: ProviderConfig, env_file: Path) -> tuple[str, str]:
    values, file_names = load_env_file(env_file)
    name = config.data["api_key_env"]
    api_key = values.get(name, "")
    if not api_key.strip():
        raise RunnerError(f"missing credential: {name}")
    source = "env_file" if name in file_names else "process_environment"
    return api_key, source


def _response_schema(pack_id: str) -> dict[str, Any]:
    schema_path = "schemas/model_report.schema.json" if pack_id == "report-v1" else "schemas/codegen_submission.schema.json"
    try:
        schema = json.loads(read_text(schema_path))
        Draft202012Validator.check_schema(schema)
        return schema
    except (json.JSONDecodeError, ContractError) as exc:
        raise RunnerError(f"invalid response schema: {schema_path}") from exc


def _validate_model_json(pack_id: str, model_text: str) -> tuple[bool, str | None]:
    try:
        parsed = json.loads(model_text)
    except json.JSONDecodeError:
        return False, "model_output_not_json"
    errors = sorted(Draft202012Validator(_response_schema(pack_id)).iter_errors(parsed), key=str)
    if errors:
        return False, f"schema_{errors[0].validator}_failed"
    if pack_id in CODEGEN_OUTPUT_PATHS:
        semantic_failure = _validate_codegen_semantics(pack_id, parsed)
        if semantic_failure:
            return False, semantic_failure
    return True, None


def _validate_codegen_semantics(pack_id: str, parsed: Any) -> str | None:
    if not isinstance(parsed, dict):
        return "codegen_output_not_object"
    expected_task = f"C{pack_id.removeprefix('codegen-c').removesuffix('-v1')}"
    if parsed.get("task_id") != expected_task:
        return "codegen_task_id_mismatch"
    seen: set[str] = set()
    seen_casefolded: set[str] = set()
    total_bytes = 0
    for item in parsed.get("files", []):
        path = item["path"]
        try:
            validate_relative_path(path)
        except ContractError:
            return "codegen_file_path_unsafe"
        if path not in CODEGEN_OUTPUT_PATHS[pack_id]:
            return "codegen_file_path_not_allowed"
        folded = path.casefold()
        if path in seen or folded in seen_casefolded:
            return "codegen_file_path_duplicate"
        seen.add(path)
        seen_casefolded.add(folded)
        content = item["content"]
        if (
            content.startswith("\ufeff")
            or "\r" in content
            or content != unicodedata.normalize("NFC", content)
        ):
            return "codegen_file_content_not_canonical"
        byte_length = len(content.encode("utf-8"))
        if byte_length > 250_000:
            return "codegen_file_content_too_large"
        total_bytes += byte_length
    if total_bytes > 1_000_000:
        return "codegen_submission_too_large"
    return None


def _model_declared_status(model_text: str | None) -> str | None:
    if model_text is None:
        return None
    try:
        parsed = json.loads(model_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    status = parsed.get("status")
    return status if status in {"completed", "incomplete", "blocked"} else None


def _persist_extracted_output(
    run_dir: Path, pack_id: str, model_text: str | None
) -> dict[str, Any]:
    """Persist exact extracted model-visible text separately from provider JSON."""
    if model_text is None:
        return {"path": None, "sha256": None, "byte_length": None, "media_type": None}
    name = "extracted_submission.json" if pack_id in CODEGEN_OUTPUT_PATHS else "extracted_report.json"
    content = model_text.encode("utf-8")
    _safe_write(run_dir / name, content)
    return {
        "path": name,
        "sha256": sha256(content),
        "byte_length": len(content),
        "media_type": "application/json",
    }


def _validate_document(record: dict[str, Any], schema_path: str, label: str) -> None:
    try:
        schema = json.loads(read_text(schema_path))
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(record),
            key=str,
        )
    except (json.JSONDecodeError, ContractError) as exc:
        raise RunnerError(f"invalid {label} contract") from exc
    if errors:
        raise RunnerError(f"{label} violates contract at {errors[0].json_path}: {errors[0].message}")


def classify_transport_error(error: BaseException) -> str:
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(reason, RemoteDisconnected):
        return "remote_disconnected"
    if isinstance(reason, ConnectionResetError):
        return "connection_reset"
    if isinstance(reason, IncompleteRead):
        return "incomplete_read"
    return "network_other"


def _set_stream_timeout(stream: Any, timeout_seconds: float) -> None:
    candidates = [stream]
    for attribute in ("fp", "raw", "_sock"):
        parent = candidates[-1]
        child = getattr(parent, attribute, None)
        if child is not None:
            candidates.append(child)
    for candidate in reversed(candidates):
        setter = getattr(candidate, "settimeout", None)
        if callable(setter):
            setter(max(timeout_seconds, 0.001))
            return


def _read_response(stream: Any, deadline: float, maximum_bytes: int = 64 * 1024 * 1024) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise TransportFailure("timeout")
        _set_stream_timeout(stream, remaining)
        try:
            chunk = stream.read(65_536)
        except (URLError, TimeoutError, socket.timeout, ConnectionResetError, RemoteDisconnected, IncompleteRead) as exc:
            raise TransportFailure(classify_transport_error(exc)) from exc
        except OSError as exc:
            raise TransportFailure(classify_transport_error(exc)) from exc
        if time.perf_counter() > deadline:
            raise TransportFailure("timeout")
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum_bytes:
            raise TransportFailure("response_too_large")


def _http_post(
    config: ProviderConfig, payload: dict[str, Any], api_key: str, deadline: float
) -> tuple[int, dict[str, str], bytes, float]:
    request = Request(
        endpoint_url(config),
        data=canonical_json_bytes(payload),
        headers=request_headers(config, api_key),
        method="POST",
    )
    start = time.perf_counter()
    opener = build_opener(NoRedirectHandler())
    try:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise TransportFailure("timeout")
        with opener.open(request, timeout=max(remaining, 0.001)) as response:
            raw = _read_response(response, deadline)
            return response.status, dict(response.headers.items()), raw, (time.perf_counter() - start) * 1000
    except HTTPError as exc:
        raw = _read_response(exc, deadline)
        headers = dict(exc.headers.items()) if exc.headers is not None else {}
        return exc.code, headers, raw, (time.perf_counter() - start) * 1000
    except TransportFailure:
        raise
    except (URLError, TimeoutError, socket.timeout, ConnectionResetError, RemoteDisconnected, IncompleteRead) as exc:
        raise TransportFailure(classify_transport_error(exc)) from exc
    except OSError as exc:
        raise TransportFailure(classify_transport_error(exc)) from exc


def _request_id(headers: dict[str, str], response: dict[str, Any] | None) -> str | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    for key in ("x-request-id", "request-id", "anthropic-request-id"):
        if lowered.get(key):
            return lowered[key]
    if response and isinstance(response.get("id"), str):
        return response["id"]
    return None


def _finish_reason(config: ProviderConfig, response: dict[str, Any]) -> str | None:
    if config.provider in {"anthropic", "minimax"}:
        value = response.get("stop_reason")
    elif config.provider in {"kimi", "deepseek"}:
        choices = response.get("choices") or []
        value = (
            choices[0].get("finish_reason")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict)
            else None
        )
    else:
        value = response.get("status")
    return value if isinstance(value, str) else None


def _json_object(raw: bytes | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _retry_after_seconds(headers: dict[str, str]) -> float | None:
    value = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            return max((when - datetime.now(timezone.utc)).total_seconds(), 0.0)
        except (TypeError, ValueError, OverflowError):
            return None


def _execute_request(
    config: ProviderConfig,
    payload: dict[str, Any],
    api_key: str,
    run_dir: Path,
    output_root: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    deadline = started + float(config.data["wall_clock_timeout_seconds"])
    attempts: list[dict[str, Any]] = []
    attempt_responses: list[dict[str, Any] | None] = []
    terminal: dict[str, Any] = {"status": None, "headers": {}, "raw": None, "json": None, "latency_ms": None}
    backoff_total = 0.0

    for number in range(1, config.data["max_transport_attempts"] + 1):
        attempt_started = utc_now()
        status: int | None = None
        headers: dict[str, str] = {}
        raw: bytes | None = None
        latency: float
        failure_code: str | None = None
        transport_code: str | None = None
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            latency = 0.0
            transport_code = "timeout"
            failure_code = "timeout"
        else:
            call_start = time.perf_counter()
            try:
                status, headers, raw, latency = _http_post(config, payload, api_key, deadline)
                if not 200 <= status < 300:
                    failure_code = f"http_{status}"
            except TransportFailure as exc:
                latency = (time.perf_counter() - call_start) * 1000
                transport_code = exc.code
                failure_code = exc.code

        response_json = _json_object(raw)
        raw_path: str | None = None
        raw_hash: str | None = None
        if raw is not None:
            raw_file = run_dir / f"attempt_{number:02d}_response.json"
            _safe_write(raw_file, raw)
            raw_path = raw_file.relative_to(output_root).as_posix()
            raw_hash = sha256(raw)

        has_more = number < config.data["max_transport_attempts"]
        retryable_failure = (
            status in config.data["transport_retry_statuses"]
            if status is not None
            else transport_code in config.data["transport_retry_errors"]
        )
        retryable = bool(failure_code and has_more and retryable_failure)
        backoff_seconds = 0.0
        if retryable:
            retry_after = _retry_after_seconds(headers)
            backoff_seconds = retry_after if retry_after is not None else min(2 ** (number - 1), 8)
            backoff_seconds = min(backoff_seconds, max(deadline - time.perf_counter(), 0.0))
            if backoff_seconds <= 0:
                retryable = False
                backoff_seconds = 0.0

        attempts.append({
            "attempt": number,
            "started_at_utc": attempt_started,
            "completed_at_utc": utc_now(),
            "elapsed_ms": round(latency, 3),
            "status_code": status,
            "request_id": _request_id(headers, response_json),
            "response_produced": status is not None,
            "raw_response_path": raw_path,
            "raw_response_sha256": raw_hash,
            "failure_code": failure_code,
            "retryable": retryable,
            "backoff_after_ms": round(backoff_seconds * 1000, 3),
        })
        attempt_responses.append(response_json)
        terminal = {"status": status, "headers": headers, "raw": raw, "json": response_json, "latency_ms": latency}
        if failure_code is None or not retryable:
            break
        time.sleep(backoff_seconds)
        backoff_total += backoff_seconds * 1000

    terminal["attempts"] = attempts
    terminal["attempt_responses"] = attempt_responses
    terminal["total_elapsed_ms"] = (time.perf_counter() - started) * 1000
    terminal["backoff_total_ms"] = backoff_total
    return terminal


def _account_attempts(
    config: ProviderConfig,
    attempts: list[dict[str, Any]],
    responses: list[dict[str, Any] | None],
    snapshot: PricingSnapshot | None,
    fallback_model_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    for attempt, response in zip(attempts, responses, strict=True):
        usage = normalize_usage(config, response) if response else dict(EMPTY_USAGE)
        model_id = returned_model_id(config, response) if response else None
        service_tier = returned_service_tier(config, response) if response else None
        attempt["usage"] = usage
        attempt["cost"] = calculate_cost(
            usage,
            snapshot,
            config.provider,
            model_id or fallback_model_id,
            service_tier or config.data["service_tier"],
        )
    aggregate_usage: dict[str, Any] = {}
    known_subtotals: dict[str, int] = {}
    missing_attempt_counts: dict[str, int] = {}
    for field in TOKEN_FIELDS:
        values = [attempt["usage"][field] for attempt in attempts]
        known = [value for value in values if value is not None]
        known_subtotals[field] = sum(known)
        missing_attempt_counts[field] = sum(value is None for value in values)
        aggregate_usage[field] = sum(known) if len(known) == len(values) else None
    aggregate_usage["integrity_valid"] = all(
        attempt["usage"]["integrity_valid"] is True for attempt in attempts
    )
    aggregate_usage["integrity_failure_code"] = (
        None if aggregate_usage["integrity_valid"] else "one_or_more_attempt_usage_incomplete"
    )
    usage_summary = {
        "known_token_subtotals": known_subtotals,
        "missing_attempt_counts": missing_attempt_counts,
    }
    aggregate_cost = sum_attempt_costs(
        [attempt["cost"] for attempt in attempts],
        snapshot,
        fallback_model_id,
        config.data["service_tier"],
    )
    return aggregate_usage, usage_summary, aggregate_cost


def _new_run_dir(output_root: Path, run_id: str | None) -> tuple[str, Path, Path]:
    safe_root = ensure_safe_output_root(output_root)
    generated = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + os.urandom(4).hex()
    if not RUN_ID_PATTERN.fullmatch(generated):
        raise RunnerError("run ID may contain only letters, numbers, dot, underscore, and hyphen")
    target = safe_root / generated
    if target.exists():
        raise RunnerError(f"run directory already exists: {generated}")
    target.mkdir(parents=True, exist_ok=False)
    return generated, target, safe_root


def _source_identity() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True
        ).stdout.decode("ascii").strip()
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=ROOT, check=True, capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError):
        commit = None
        status = b"git_unavailable\n"

    source_paths: list[Path] = []
    for relative, suffix in (
        ("src/soa_benchmark", ".py"),
        ("benchmark_contracts", ".json"),
        ("configs/providers", ".json"),
        ("schemas", ".json"),
    ):
        source_paths.extend(
            path for path in (ROOT / relative).rglob(f"*{suffix}") if path.is_file()
        )
    source_paths.append(ROOT / "scripts/run_benchmark.py")
    source_paths.append(ROOT / "prompts/prompt_manifest.json")
    source_paths.append(ROOT / "configs/pricing/pricing_manifest.json")
    source_paths.append(ROOT / "pyproject.toml")
    source_paths.append(ROOT / "requirements-benchmark.lock")
    source_bundle = bytearray(b"RUNNER-SOURCE/1\n")
    for path in sorted(set(source_paths), key=lambda item: item.relative_to(ROOT).as_posix()):
        relative = path.relative_to(ROOT).as_posix()
        source_bundle.extend(length_prefixed("PATH", relative.encode("utf-8")))
        source_bundle.extend(length_prefixed("CONTENT", path.read_bytes()))
    return {
        "source_git_commit": commit,
        "source_tree_dirty": bool(status),
        "source_status_sha256": sha256(status),
        "runner_source_sha256": sha256(bytes(source_bundle)),
    }


def _response_has_raw_reasoning(config: ProviderConfig, response: dict[str, Any]) -> bool:
    if config.provider in {"anthropic", "minimax"}:
        content = response.get("content")
        return isinstance(content, list) and any(
            isinstance(item, dict)
            and item.get("type") == "thinking"
            and isinstance(item.get("thinking"), str)
            and bool(item["thinking"])
            for item in content
        )
    if config.provider in {"kimi", "deepseek"}:
        choices = response.get("choices")
        if not isinstance(choices, list):
            return False
        return any(
            isinstance(choice, dict)
            and isinstance(choice.get("message"), dict)
            and isinstance(choice["message"].get("reasoning_content"), str)
            and bool(choice["message"]["reasoning_content"])
            for choice in choices
        )
    return False


def _replay(
    config: ProviderConfig,
    responses: list[dict[str, Any] | None],
    identity: dict[str, Any],
) -> dict[str, Any]:
    try:
        jsonschema_version = version("jsonschema")
    except PackageNotFoundError:
        jsonschema_version = "not-installed"
    return {
        "runner_version": RUNNER_VERSION,
        "python_version": os.sys.version.split()[0],
        "dependency_versions": {"jsonschema": jsonschema_version},
        "raw_reasoning_stored": any(
            response is not None and _response_has_raw_reasoning(config, response)
            for response in responses
        ),
        **identity,
    }


def preflight(
    prompt: RenderedPrompt,
    provider_config_paths: tuple[str, ...] = DEFAULT_PROVIDER_CONFIGS,
) -> dict[str, Any]:
    """Verify all envelopes preserve the exact same visible prompt bytes."""
    providers = []
    for path in provider_config_paths:
        config = load_provider_config(path)
        payload = build_payload(config, prompt)
        providers.append({
            "provider_alias": config.alias,
            "provider": config.provider,
            "config_sha256": config.sha256,
            "request_body_sha256": sha256(canonical_json_bytes(payload)),
            "model_visible_sha256": model_visible_hash_from_payload(config.provider, payload),
        })
    hashes = {item["model_visible_sha256"] for item in providers}
    if hashes != {prompt.model_visible_sha256}:
        raise RunnerError("provider envelopes do not preserve canonical model-visible bytes")
    aliases = [item["provider_alias"] for item in providers]
    routes = [item["provider"] for item in providers]
    if len(aliases) != len(set(aliases)) or len(routes) != len(set(routes)):
        raise RunnerError("provider configs must have unique aliases and provider routes")
    return {
        "schema_version": "1.0.0",
        "status": "preflight_passed",
        "pack_id": prompt.pack_id,
        "static_pack_sha256": prompt.static_pack_sha256,
        "input_manifest_sha256": prompt.input_manifest_sha256,
        "input_bundle_sha256": prompt.input_bundle_sha256,
        "model_visible_sha256": prompt.model_visible_sha256,
        "providers": providers,
    }


def _load_live_pricing(config: ProviderConfig, pricing_snapshot_path: str) -> PricingSnapshot:
    try:
        if config.data["configuration_state"] != "frozen":
            raise PricingError("provider_configuration_not_frozen")
        snapshot = load_live_pricing_snapshot(pricing_snapshot_path)
        require_frozen_price(
            snapshot,
            config.provider,
            config.data.get("effective_model_id"),
            config.data["service_tier"],
        )
        return snapshot
    except PricingError as exc:
        raise RunnerError(f"pricing gate failed: {exc}") from exc


def run_once(
    prompt: RenderedPrompt,
    provider_config_path: str,
    env_file: Path,
    output_root: Path,
    pricing_snapshot_path: str,
    run_id: str | None = None,
    cache_lane: str = "primary_quality_repeatability",
    run_stage: str = "pilot",
) -> Path:
    """Run one priced request with a total deadline and a complete attempt ledger."""
    if run_stage not in {"pilot", "confirmatory"}:
        raise RunnerError("run stage must be pilot or confirmatory")
    safe_root = ensure_safe_output_root(output_root)
    config = load_provider_config(provider_config_path)
    api_key, credential_source = _credential(config, env_file)
    snapshot = _load_live_pricing(config, pricing_snapshot_path)
    identity = _source_identity()
    if run_stage == "confirmatory" and identity["source_tree_dirty"]:
        raise RunnerError("confirmatory runs require a clean source tree")
    payload = build_payload(config, prompt)
    request_body = canonical_json_bytes(payload)
    run_id, run_dir, safe_root = _new_run_dir(safe_root, run_id)
    started_at = utc_now()
    result = _execute_request(config, payload, api_key, run_dir, safe_root)
    response_json = result["json"]
    status_code = result["status"]
    raw = result["raw"]
    attempts = result["attempts"]

    model_text: str | None = None
    schema_valid = False
    validation_failure: str | None = "transport_failure" if status_code is None else f"http_{status_code}"
    if response_json is not None and status_code is not None and 200 <= status_code < 300:
        try:
            model_text = extract_text(config, response_json)
            schema_valid, validation_failure = _validate_model_json(prompt.pack_id, model_text)
        except ProviderError:
            validation_failure = "response_extraction_failed"
    extracted_output = _persist_extracted_output(run_dir, prompt.pack_id, model_text)
    model_declared_status = _model_declared_status(model_text)

    returned_id = returned_model_id(config, response_json) if response_json else None
    returned_tier = returned_service_tier(config, response_json) if response_json else None
    if returned_id and returned_id != config.data.get("effective_model_id"):
        schema_valid = False
        validation_failure = "returned_model_mismatch"
    if returned_tier and returned_tier != config.data["service_tier"]:
        schema_valid = False
        validation_failure = "returned_service_tier_mismatch"
    model_for_cost = returned_id or config.data.get("effective_model_id")
    usage, usage_summary, cost = _account_attempts(
        config,
        attempts,
        result["attempt_responses"],
        snapshot,
        model_for_cost,
    )
    terminal_attempt = attempts[-1]
    record = {
        "schema_version": "1.2.0",
        "run_id": run_id,
        "run_stage": run_stage,
        "status": "response_contract_valid" if schema_valid else "failed",
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "cache_lane": cache_lane,
        "cache_lane_policy": "observational_only_no_cache_state_guarantee",
        "prompt": {
            "pack_id": prompt.pack_id,
            "static_pack_sha256": prompt.static_pack_sha256,
            "input_manifest_sha256": prompt.input_manifest_sha256,
            "input_bundle_sha256": prompt.input_bundle_sha256,
            "model_visible_sha256": prompt.model_visible_sha256,
        },
        "provider": {
            "alias": config.alias,
            "provider": config.provider,
            "requested_model_id": config.data["requested_model_id"],
            "effective_model_id": config.data.get("effective_model_id"),
            "returned_model_id": returned_id,
            "requested_service_tier": config.data["service_tier"],
            "returned_service_tier": returned_tier,
            "config_sha256": config.sha256,
            "request_body_sha256": sha256(request_body),
            "credential_source": credential_source,
        },
        "attempts": attempts,
        "response": {
            "http_status": status_code,
            "request_id": terminal_attempt["request_id"],
            "finish_reason": _finish_reason(config, response_json) if response_json else None,
            "raw_response_path": terminal_attempt["raw_response_path"],
            "raw_response_sha256": sha256(raw) if raw is not None else None,
        },
        "extracted_output": extracted_output,
        "metrics": {
            "total_elapsed_ms": round(result["total_elapsed_ms"], 3),
            "final_attempt_latency_ms": round(result["latency_ms"], 3) if result["latency_ms"] is not None else None,
            "backoff_total_ms": round(result["backoff_total_ms"], 3),
            "time_to_first_token_ms": None,
            "time_to_first_token_reason_code": "non_streaming_request",
        },
        "usage": usage,
        "usage_summary": usage_summary,
        "cost": cost,
        "validation": {
            "response_schema_valid": schema_valid,
            "failure_code": validation_failure,
            "model_output_sha256": sha256(model_text.encode("utf-8")) if model_text is not None else None,
            "acceptance_scope": "transport_and_output_contract_only",
            "model_declared_status": model_declared_status,
        },
        "replay": _replay(config, result["attempt_responses"], identity),
    }
    _validate_document(record, "benchmark_contracts/run_manifest.schema.json", "run manifest")
    output = run_dir / "run_manifest.json"
    _safe_write(output, canonical_json_bytes(record))
    return output


def _aggregate_manifests(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    token_fields = TOKEN_FIELDS
    token_totals = {field: 0 for field in token_fields}
    token_missing_runs = {field: 0 for field in token_fields}
    known_token_subtotals = {field: 0 for field in token_fields}
    missing_attempt_counts = {field: 0 for field in token_fields}
    known_cost = Decimal("0")
    unknown_cost_runs = 0
    incomplete_attempt_count = 0
    for manifest in manifests:
        for field in token_fields:
            known_token_subtotals[field] += manifest["usage_summary"]["known_token_subtotals"][field]
            missing_attempt_counts[field] += manifest["usage_summary"]["missing_attempt_counts"][field]
            value = manifest["usage"][field]
            if value is None:
                token_missing_runs[field] += 1
            else:
                token_totals[field] += value
        known_cost += Decimal(manifest["cost"]["known_subtotal_usd"])
        incomplete_attempt_count += manifest["cost"]["incomplete_attempt_count"]
        if not manifest["cost"]["complete"]:
            unknown_cost_runs += 1
    return {
        "run_count": len(manifests),
        "token_totals": token_totals,
        "token_missing_runs": token_missing_runs,
        "known_token_subtotals": known_token_subtotals,
        "missing_attempt_counts": missing_attempt_counts,
        "known_cost_usd": format(known_cost.quantize(Decimal("0.000000000001")), "f"),
        "unknown_cost_runs": unknown_cost_runs,
        "incomplete_attempt_count": incomplete_attempt_count,
        "cost_complete": unknown_cost_runs == 0,
    }


def run_matrix(
    prompt: RenderedPrompt,
    provider_config_paths: tuple[str, ...],
    env_file: Path,
    output_root: Path,
    pricing_snapshot_path: str,
    repetitions: int,
    batch_id: str | None = None,
    cache_lane: str = "primary_quality_repeatability",
    run_stage: str = "pilot",
) -> Path:
    """Execute all preregistered runs in a rotation-balanced provider order."""
    if repetitions < 1 or repetitions > 20:
        raise RunnerError("repetitions must be between 1 and 20")
    provider_count = len(provider_config_paths)
    if provider_count < 1:
        raise RunnerError("at least one provider config is required")
    if provider_count > 1 and repetitions % provider_count != 0:
        raise RunnerError("balanced matrix repetitions must be a multiple of the provider count")
    safe_root = ensure_safe_output_root(output_root)
    preflight_result = preflight(prompt, provider_config_paths)
    snapshot = load_live_pricing_snapshot(pricing_snapshot_path)
    identity = _source_identity()
    if run_stage == "confirmatory" and identity["source_tree_dirty"]:
        raise RunnerError("confirmatory runs require a clean source tree")
    for config_path in provider_config_paths:
        config = load_provider_config(config_path)
        _credential(config, env_file)
        try:
            if config.data["configuration_state"] != "frozen":
                raise PricingError("provider_configuration_not_frozen")
            require_frozen_price(
                snapshot,
                config.provider,
                config.data.get("effective_model_id"),
                config.data["service_tier"],
            )
        except PricingError as exc:
            raise RunnerError(f"pricing gate failed for {config.alias}: {exc}") from exc

    generated = batch_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-matrix"
    if not RUN_ID_PATTERN.fullmatch(generated):
        raise RunnerError("batch ID may contain only letters, numbers, dot, underscore, and hyphen")
    batch_dir = safe_root / generated
    if batch_dir.exists():
        raise RunnerError(f"batch directory already exists: {generated}")
    batch_dir.mkdir(parents=True, exist_ok=False)
    started_at = utc_now()

    outcomes: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    for repetition in range(1, repetitions + 1):
        shift = (repetition - 1) % provider_count
        ordered = provider_config_paths[shift:] + provider_config_paths[:shift]
        for order_index, config_path in enumerate(ordered, start=1):
            config = load_provider_config(config_path)
            run_id = f"{config.alias}-r{repetition:02d}"
            manifest_path = run_once(
                prompt=prompt,
                provider_config_path=config_path,
                env_file=env_file,
                output_root=batch_dir,
                pricing_snapshot_path=pricing_snapshot_path,
                run_id=run_id,
                cache_lane=cache_lane,
                run_stage=run_stage,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifests.append(manifest)
            outcomes.append({
                "provider_alias": config.alias,
                "repetition": repetition,
                "execution_order": order_index,
                "status": manifest["status"],
                "run_manifest_path": manifest_path.relative_to(batch_dir).as_posix(),
            })
    batch_manifest = {
        "schema_version": "1.2.0",
        "batch_id": generated,
        "run_stage": run_stage,
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "cache_lane": cache_lane,
        "cache_lane_policy": "observational_only_no_cache_state_guarantee",
        "planned_repetitions": repetitions,
        "preflight": preflight_result,
        "pricing_snapshot_id": snapshot.snapshot_id,
        "pricing_snapshot_sha256": snapshot.sha256,
        "outcomes": outcomes,
        "aggregate": _aggregate_manifests(manifests),
        "execution_order_rule": "cyclic_rotation_by_repetition",
        "selection_rule": "all_preregistered_repetitions; repetition_1_is_example_only",
    }
    _validate_document(batch_manifest, "benchmark_contracts/batch_manifest.schema.json", "batch manifest")
    output = batch_dir / "batch_manifest.json"
    _safe_write(output, canonical_json_bytes(batch_manifest))
    return output


def validate_probe_output(model_text: str | None) -> tuple[bool, str | None]:
    if model_text is None:
        return False, "probe_output_missing"
    try:
        value = json.loads(model_text)
    except json.JSONDecodeError:
        return False, "probe_output_not_json"
    if not isinstance(value, dict) or value != {"ok": True}:
        return False, "probe_output_not_exact"
    return True, None


def capability_probe(
    provider_config_path: str,
    env_file: Path,
    output_root: Path,
    probe_id: str | None = None,
    pricing_snapshot_path: str | None = None,
) -> Path:
    """Probe a route and persist evidence even when the transport fails."""
    safe_root = ensure_safe_output_root(output_root)
    config = load_provider_config(provider_config_path)
    api_key, credential_source = _credential(config, env_file)
    snapshot = load_live_pricing_snapshot(pricing_snapshot_path) if pricing_snapshot_path else None
    identity = _source_identity()
    system = "Return only the JSON object requested by the user.\n"
    user = "Return exactly {\"ok\":true}.\n"
    visible = length_prefixed("SYSTEM", system.encode("utf-8")) + length_prefixed("USER", user.encode("utf-8"))
    prompt = RenderedPrompt(
        pack_id="capability-probe-v1",
        static_pack_sha256="0" * 64,
        input_manifest_sha256="0" * 64,
        input_bundle_sha256="0" * 64,
        system=system,
        user=user,
        model_visible_sha256=sha256(visible),
    )
    payload = build_payload(config, prompt)
    if config.provider == "openai":
        payload["max_output_tokens"] = PROBE_MAX_OUTPUT_TOKENS
    else:
        payload["max_tokens"] = PROBE_MAX_OUTPUT_TOKENS
    probe_id, probe_dir, safe_root = _new_run_dir(safe_root, probe_id)
    started_at = utc_now()
    result = _execute_request(config, payload, api_key, probe_dir, safe_root)
    response = result["json"]
    status_code = result["status"]
    attempts = result["attempts"]
    model_text: str | None = None
    extraction_failure: str | None = None
    if response is not None and status_code is not None and 200 <= status_code < 300:
        try:
            model_text = extract_text(config, response)
        except ProviderError:
            extraction_failure = "response_extraction_failed"
    exact, exact_failure = validate_probe_output(model_text)
    failure = extraction_failure or exact_failure
    returned_id = returned_model_id(config, response) if response else None
    returned_tier = returned_service_tier(config, response) if response else None
    model_for_cost = returned_id or config.data["requested_model_id"]
    usage, usage_summary, cost = _account_attempts(
        config,
        attempts,
        result["attempt_responses"],
        snapshot,
        model_for_cost,
    )
    if status_code is None:
        probe_status = "transport_failed"
        failure = attempts[-1]["failure_code"]
    elif not 200 <= status_code < 300:
        probe_status = "rejected"
        failure = f"http_{status_code}"
    else:
        probe_status = "accepted" if exact else "rejected"
    terminal_attempt = attempts[-1]
    record = {
        "schema_version": "1.0.0",
        "probe_id": probe_id,
        "status": probe_status,
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "provider": {
            "alias": config.alias,
            "provider": config.provider,
            "requested_model_id": config.data["requested_model_id"],
            "returned_model_id": returned_id,
            "requested_service_tier": config.data["service_tier"],
            "returned_service_tier": returned_tier,
            "config_sha256": config.sha256,
            "credential_source": credential_source,
        },
        "request": {
            "endpoint": endpoint_url(config),
            "request_body_sha256": sha256(canonical_json_bytes(payload)),
            "model_visible_sha256": prompt.model_visible_sha256,
            "requested_reasoning_settings": config.data.get("native_reasoning_settings"),
            "requested_max_output_tokens": PROBE_MAX_OUTPUT_TOKENS,
        },
        "attempts": attempts,
        "response": {
            "http_status": status_code,
            "request_id": terminal_attempt["request_id"],
            "finish_reason": _finish_reason(config, response) if response else None,
            "raw_response_path": terminal_attempt["raw_response_path"],
            "raw_response_sha256": terminal_attempt["raw_response_sha256"],
        },
        "metrics": {
            "total_elapsed_ms": round(result["total_elapsed_ms"], 3),
            "final_attempt_latency_ms": round(result["latency_ms"], 3) if result["latency_ms"] is not None else None,
            "backoff_total_ms": round(result["backoff_total_ms"], 3),
        },
        "usage": usage,
        "usage_summary": usage_summary,
        "cost": cost,
        "validation": {
            "exact_json_object_valid": exact,
            "failure_code": failure,
            "model_output_sha256": sha256(model_text.encode("utf-8")) if model_text is not None else None,
        },
        "replay": _replay(config, result["attempt_responses"], identity),
        "next_gate": "freeze_effective_model_id_and_matching_pricing_before_paid_benchmark_runs",
    }
    _validate_document(record, "benchmark_contracts/capability_probe.schema.json", "capability probe")
    output = probe_dir / "capability_probe.json"
    _safe_write(output, canonical_json_bytes(record))
    return output
