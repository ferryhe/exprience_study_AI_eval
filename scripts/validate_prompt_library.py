"""Offline validation for the provider-neutral prompt library."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "prompts" / "prompt_manifest.json"
DENIED_ROOTS = (
    "data/",
    "gold/",
    "tests/hidden/",
    "reference_implementation/",
    "outputs/",
    "runs/",
)
PROVIDER_IDENTITIES = re.compile(
    r"(?i)\b(openai|anthropic|deepseek|kimi|moonshot|claude|gpt-[0-9])\b"
)
WINDOWS_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class ValidationError(ValueError):
    """Raised when a freeze-blocking prompt-library check fails."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bytes(relative_path: str) -> bytes:
    path = ROOT / relative_path
    if path.is_symlink():
        raise ValidationError(f"symlink is forbidden: {relative_path}")
    if not path.is_file():
        raise ValidationError(f"missing artifact: {relative_path}")
    return path.read_bytes()


def validate_text(relative_path: str, data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        raise ValidationError(f"UTF-8 BOM is forbidden: {relative_path}")
    if b"\r" in data:
        raise ValidationError(f"non-LF line ending: {relative_path}")
    if not data.endswith(b"\n"):
        raise ValidationError(f"terminal newline missing: {relative_path}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"invalid UTF-8: {relative_path}") from exc
    if text != unicodedata.normalize("NFC", text):
        raise ValidationError(f"text is not Unicode NFC: {relative_path}")
    return text


def media_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix
    return {
        ".json": "application/json",
        ".md": "text/markdown",
    }.get(suffix, "text/plain")


def length_prefixed(label: str, value: bytes) -> bytes:
    return f"{label} {len(value)}\n".encode("ascii") + value + b"\n"


def serialize_role(role: str, components: list[dict[str, str]]) -> bytes:
    result = bytearray(b"CPACK-ROLE/1\n")
    result.extend(length_prefixed("ROLE", role.encode("ascii")))
    for index, component in enumerate(components, start=1):
        path = component["path"]
        content = read_bytes(path)
        result.extend(f"RECORD {index}\n".encode("ascii"))
        result.extend(length_prefixed("PATH", path.encode("utf-8")))
        result.extend(length_prefixed("MEDIA_TYPE", media_type(path).encode("ascii")))
        result.extend(length_prefixed("SHA256", sha256(content).encode("ascii")))
        result.extend(length_prefixed("CONTENT", content))
    return bytes(result)


def serialize_pack(components: list[dict[str, str]]) -> tuple[bytes, str, str]:
    system = serialize_role(
        "system", [item for item in components if item["role"] == "system"]
    )
    user = serialize_role(
        "user", [item for item in components if item["role"] == "user"]
    )
    pack = (
        b"CPACK/1\n"
        + length_prefixed("SYSTEM", system)
        + length_prefixed("USER", user)
    )
    return pack, system.decode("utf-8"), user.decode("utf-8")


def provider_payload(
    provider: str, config: dict[str, Any], system: str, user: str
) -> dict[str, Any]:
    common = {
        "model": config["requested_model_id"],
        "max_output_tokens": config["max_output_tokens"],
    }
    if provider == "openai":
        return {
            **common,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": [{"type": "input_text", "text": user}]},
            ],
        }
    if provider == "anthropic":
        return {
            "model": common["model"],
            "max_tokens": common["max_output_tokens"],
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
    return {
        **common,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }


def extract_model_visible(provider: str, payload: dict[str, Any]) -> tuple[str, str]:
    if provider == "openai":
        return (
            payload["input"][0]["content"][0]["text"],
            payload["input"][1]["content"][0]["text"],
        )
    if provider == "anthropic":
        return payload["system"], payload["messages"][0]["content"]
    return payload["messages"][0]["content"], payload["messages"][1]["content"]


def validate_submission_path(path_text: str) -> None:
    if not path_text or "\x00" in path_text or "\\" in path_text or ":" in path_text:
        raise ValidationError(f"unsafe submission path: {path_text!r}")
    if path_text != unicodedata.normalize("NFC", path_text):
        raise ValidationError(f"non-NFC submission path: {path_text!r}")
    path = PurePosixPath(path_text)
    if (
        path.is_absolute()
        or path.as_posix() != path_text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValidationError(f"unsafe submission path: {path_text!r}")
    if any(part.split(".")[0].upper() in WINDOWS_DEVICE_NAMES for part in path.parts):
        raise ValidationError(f"device-name submission path: {path_text!r}")


def validate_malicious_paths() -> None:
    rejected = (
        "../secret.txt",
        "/absolute.py",
        "C:/absolute.py",
        "src\\escape.py",
        "src/../escape.py",
        "NUL.txt",
        "src/COM1.py",
        "src/evil\x00.py",
    )
    for path in rejected:
        try:
            validate_submission_path(path)
        except ValidationError:
            continue
        raise ValidationError(f"malicious path was accepted: {path!r}")
    validate_submission_path("src/soa_experience/calculations/actual_to_expected.py")


def expected_artifact_paths() -> set[str]:
    paths: set[str] = set()
    patterns = (
        "configs/providers/*.json",
        "prompts/common/**/*.md",
        "prompts/report/**/*.md",
        "prompts/codegen/**/*.md",
        "prompts/manifest_examples/**/*.json",
        "schemas/*.json",
    )
    for pattern in patterns:
        for path in ROOT.glob(pattern):
            relative = path.relative_to(ROOT).as_posix()
            if relative != "prompts/prompt_manifest.json":
                paths.add(relative)
    return paths


def parse_json(relative_path: str) -> Any:
    data = read_bytes(relative_path)
    validate_text(relative_path, data)
    try:
        return json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON: {relative_path}: {exc}") from exc


def validate_manifest(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    required_top = {
        "schema_version",
        "library_version",
        "status",
        "canonicalization",
        "artifacts",
        "packs",
        "review",
    }
    if set(manifest) != required_top:
        raise ValidationError("prompt manifest has unexpected or missing top-level keys")
    if manifest["status"] != "draft":
        raise ValidationError("preparation-stage manifest must remain draft")

    by_path: dict[str, dict[str, Any]] = {}
    for artifact in manifest["artifacts"]:
        path = artifact["path"]
        validate_submission_path(path)
        if path in by_path:
            raise ValidationError(f"duplicate manifest artifact: {path}")
        data = read_bytes(path)
        validate_text(path, data)
        if artifact["byte_length"] != len(data):
            raise ValidationError(f"byte length mismatch: {path}")
        if artifact["sha256"] != sha256(data):
            raise ValidationError(f"SHA-256 mismatch: {path}")
        if artifact["media_type"] != media_type(path):
            raise ValidationError(f"media type mismatch: {path}")
        if path.endswith(".json"):
            parse_json(path)
        by_path[path] = artifact

    expected = expected_artifact_paths()
    if set(by_path) != expected:
        missing = sorted(expected - set(by_path))
        extra = sorted(set(by_path) - expected)
        raise ValidationError(f"manifest coverage mismatch; missing={missing}; extra={extra}")
    return by_path


def validate_packs(manifest: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> None:
    pack_ids: set[str] = set()
    required_pack_ids = {"report-v1", *(f"codegen-c{number}-v1" for number in range(1, 8))}
    configs = {
        config["provider"]: config
        for config in (
            parse_json("configs/providers/openai.json"),
            parse_json("configs/providers/anthropic.json"),
            parse_json("configs/providers/kimi.json"),
            parse_json("configs/providers/deepseek.json"),
        )
    }

    for pack_definition in manifest["packs"]:
        pack_id = pack_definition["pack_id"]
        if pack_id in pack_ids:
            raise ValidationError(f"duplicate pack ID: {pack_id}")
        pack_ids.add(pack_id)
        components = pack_definition["components"]
        for component in components:
            path = component["path"]
            if path not in artifacts:
                raise ValidationError(f"unregistered pack component: {path}")
            if any(path.startswith(root) for root in DENIED_ROOTS):
                raise ValidationError(f"denied pack component: {path}")
            if artifacts[path]["purpose"] not in {"prompt", "schema"}:
                raise ValidationError(f"non-model artifact in pack: {path}")

        pack, system, user = serialize_pack(components)
        if pack_definition["pack_sha256"] != sha256(pack):
            raise ValidationError(f"pack SHA-256 mismatch: {pack_id}")
        if "PROMPT_PACK_LEAKAGE_CANARY" in system or "PROMPT_PACK_LEAKAGE_CANARY" in user:
            raise ValidationError(f"leakage canary entered pack: {pack_id}")
        if PROVIDER_IDENTITIES.search(system) or PROVIDER_IDENTITIES.search(user):
            raise ValidationError(f"provider identity entered canonical content: {pack_id}")

        expected_visible = (system, user)
        visible_hashes: set[str] = set()
        for provider, config in configs.items():
            payload = provider_payload(provider, config, system, user)
            payload_again = provider_payload(provider, config, system, user)
            if payload != payload_again:
                raise ValidationError(f"nondeterministic mock adapter: {provider}")
            extracted = extract_model_visible(provider, payload)
            if extracted != expected_visible:
                raise ValidationError(f"model-visible mismatch: {pack_id}/{provider}")
            visible_bytes = (
                length_prefixed("SYSTEM", extracted[0].encode("utf-8"))
                + length_prefixed("USER", extracted[1].encode("utf-8"))
            )
            visible_hashes.add(sha256(visible_bytes))
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(visible_hashes) != 1:
            raise ValidationError(f"provider-visible hashes differ: {pack_id}")
        if len(pack) > 2_000_000:
            raise ValidationError(f"prompt-only pack exceeds preflight byte limit: {pack_id}")

    if pack_ids != required_pack_ids:
        raise ValidationError(
            f"pack set mismatch; expected={sorted(required_pack_ids)}; actual={sorted(pack_ids)}"
        )


def validate_provider_state(config: dict[str, Any]) -> None:
    state = config.get("configuration_state")
    if state == "pre_probe":
        if (
            config["effective_model_id"] is not None
            or config["effective_model_reason_code"] != "not_probed"
            or config["version_semantics"] != "resolve_at_pilot_freeze"
        ):
            raise ValidationError("pre-probe provider state is inconsistent")
    elif state == "frozen":
        if (
            not isinstance(config["effective_model_id"], str)
            or not config["effective_model_id"]
            or config["effective_model_reason_code"] != "capability_probe_confirmed"
            or config["version_semantics"] != "pinned_exact"
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", config.get("capability_probe_date", ""))
        ):
            raise ValidationError("frozen provider state is inconsistent")
    else:
        raise ValidationError("provider configuration_state is invalid")
    expected_tier = "default" if config["provider"] == "openai" else "standard"
    if config.get("service_tier") != expected_tier:
        raise ValidationError(f"unexpected service tier: {config['provider']}")


def validate_provider_configs() -> None:
    configs = [parse_json(f"configs/providers/{name}.json") for name in ("openai", "anthropic", "kimi", "deepseek")]
    aliases = {config["benchmark_alias"] for config in configs}
    if aliases != {"gpt-5.6-sol", "claude-opus-5", "kimi-k3", "deepseek-v4-pro"}:
        raise ValidationError("provider alias set differs from the approved matrix")
    for config in configs:
        validate_provider_state(config)
        if not config["api_key_env"].endswith("_API_KEY"):
            raise ValidationError(f"unexpected API key environment name: {config['provider']}")
        serialized = json.dumps(config).lower()
        if "sk-" in serialized or "bearer " in serialized:
            raise ValidationError(f"possible credential in config: {config['provider']}")
        if config["primary_response_mode"] != "json_only_local_validation":
            raise ValidationError(f"unfair primary response mode: {config['provider']}")
        if config["tools_enabled"] or config["max_turns"] != 1:
            raise ValidationError(f"primary tool/turn rule violated: {config['provider']}")


def validate_schema_basics() -> None:
    for name in ("prompt_manifest", "model_report", "codegen_submission"):
        schema = parse_json(f"schemas/{name}.schema.json")
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ValidationError(f"unexpected JSON Schema draft: {name}")
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ValidationError(f"schema is not a closed root object: {name}")


def validate_schema_instances(manifest: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
    except ImportError as exc:
        raise ValidationError(
            "jsonschema is required for offline instance validation"
        ) from exc

    schemas = {
        name: parse_json(f"schemas/{name}.schema.json")
        for name in ("prompt_manifest", "model_report", "codegen_submission")
    }
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)

    Draft202012Validator(schemas["prompt_manifest"]).validate(manifest)

    code_submission = {
        "schema_version": "1.0.0",
        "task_id": "C4",
        "status": "incomplete",
        "summary": "A valid minimal offline schema fixture.",
        "files": [],
        "assumptions": [],
        "known_limitations": ["Starter interfaces are not part of this fixture."],
        "evaluator_tests": ["Run the registered task test suite."],
        "blocking_reason": None,
    }
    Draft202012Validator(schemas["codegen_submission"]).validate(code_submission)
    invalid_code_submission = {**code_submission, "unexpected": True}
    try:
        Draft202012Validator(schemas["codegen_submission"]).validate(
            invalid_code_submission
        )
    except JsonSchemaValidationError:
        pass
    else:
        raise ValidationError("code-submission schema accepted an extra property")

    section_ids = [
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
    ]
    paragraph = {"text": "A valid offline schema fixture.", "claim_ids": []}
    report = {
        "schema_version": "1.0.0",
        "report_title": "Schema fixture",
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
        "word_counts": {"main_report": 0, "practitioner_summary": 0},
    }
    Draft202012Validator(schemas["model_report"]).validate(report)
    invalid_report = {**report, "word_counts": {"main_report": -1, "practitioner_summary": 0}}
    try:
        Draft202012Validator(schemas["model_report"]).validate(invalid_report)
    except JsonSchemaValidationError:
        pass
    else:
        raise ValidationError("model-report schema accepted a negative word count")


def main() -> int:
    try:
        manifest = parse_json("prompts/prompt_manifest.json")
        validate_schema_basics()
        validate_schema_instances(manifest)
        validate_provider_configs()
        artifacts = validate_manifest(manifest)
        validate_malicious_paths()
        validate_packs(manifest, artifacts)
    except (KeyError, TypeError, ValidationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "PASS: prompt library is internally consistent "
        f"({len(artifacts)} artifacts, {len(manifest['packs'])} packs, 4 mock adapters)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
