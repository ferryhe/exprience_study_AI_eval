"""Canonical prompt and approved-input assembly for benchmark runs."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
from typing import Any
import unicodedata


ROOT = Path(__file__).resolve().parents[2]
DENIED_ROOTS = (
    "data/",
    "gold/",
    "tests/hidden/",
    "reference_implementation/",
    "outputs/",
    "runs/",
)
STATIC_SOURCE_ROOTS = ("prompts/", "schemas/", "configs/", "benchmark_contracts/", "fixtures/")
INPUT_ROOT_BY_PACK_TYPE = {
    "codegen": "fixtures/codegen/",
    "report": "fixtures/report/",
}
APPROVED_ARTIFACTS_BY_PACK = {
    "codegen-c4-v1": {
        "fixtures/codegen/c4/starter/src/soa_experience/calculations/interfaces.py",
        "fixtures/codegen/c4/ae_small.json",
        "fixtures/codegen/c4/public_contract.md",
        "fixtures/codegen/c4/requirements.lock",
    },
    "report-v1": {
        "fixtures/report/small_evidence/validation_summary.json",
        "fixtures/report/small_evidence/overview.csv",
        "fixtures/report/small_evidence/product_summary.csv",
        "fixtures/report/small_evidence/methodology.json",
        "fixtures/report/small_evidence/limitations.json",
    },
}
COMMON_SYSTEM_COMPONENTS = (
    "prompts/common/v1/system.md",
    "prompts/common/v1/evidence_rules.md",
    "prompts/common/v1/output_rules.md",
)
CODEGEN_TASK_COMPONENTS = {
    f"codegen-c{number}-v1": f"prompts/codegen/v1/tasks/{number:02d}_{name}.md"
    for number, name in enumerate(
        (
            "ingestion_schema",
            "validation_rules",
            "population_filters",
            "actual_to_expected",
            "segmented_exhibits",
            "poisson_glm",
            "integration",
        ),
        start=1,
    )
}


def _expected_pack_components(pack_id: str) -> list[dict[str, str]] | None:
    if pack_id == "report-v1":
        user_paths = (
            "prompts/report/v1/user.md",
            "prompts/report/v1/report_outline.md",
            "prompts/report/v1/limitation_checklist.md",
            "prompts/report/v1/style_guide.md",
            "schemas/model_report.schema.json",
        )
    elif pack_id in CODEGEN_TASK_COMPONENTS:
        user_paths = (
            "prompts/codegen/v1/shared_instructions.md",
            CODEGEN_TASK_COMPONENTS[pack_id],
            "schemas/codegen_submission.schema.json",
        )
    else:
        return None
    return [
        *({"role": "system", "path": path} for path in COMMON_SYSTEM_COMPONENTS),
        *({"role": "user", "path": path} for path in user_paths),
    ]
WINDOWS_DEVICE_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class ContractError(ValueError):
    """Raised when a benchmark input violates a frozen contract."""


@dataclass(frozen=True)
class RenderedPrompt:
    """Exactly the model-visible texts and their reproducibility identities."""

    pack_id: str
    static_pack_sha256: str
    input_manifest_sha256: str
    input_bundle_sha256: str
    system: str
    user: str
    model_visible_sha256: str


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def length_prefixed(label: str, value: bytes) -> bytes:
    return f"{label} {len(value)}\n".encode("ascii") + value + b"\n"


def read_text(relative_path: str) -> str:
    data = read_bytes(relative_path)
    if data.startswith(b"\xef\xbb\xbf"):
        raise ContractError(f"UTF-8 BOM is forbidden: {relative_path}")
    if b"\r" in data or not data.endswith(b"\n"):
        raise ContractError(f"canonical LF text is required: {relative_path}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"invalid UTF-8: {relative_path}") from exc
    if text != unicodedata.normalize("NFC", text):
        raise ContractError(f"Unicode NFC is required: {relative_path}")
    return text


def canonical_json_document(value: Any) -> bytes:
    """Canonical, human-readable JSON used for model-visible JSON artifacts."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def validate_relative_path(path_text: str) -> PurePosixPath:
    if not path_text or "\x00" in path_text or "\\" in path_text or ":" in path_text:
        raise ContractError(f"unsafe relative path: {path_text!r}")
    if path_text != unicodedata.normalize("NFC", path_text):
        raise ContractError(f"non-NFC relative path: {path_text!r}")
    path = PurePosixPath(path_text)
    if (
        path.is_absolute()
        or path.as_posix() != path_text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ContractError(f"unsafe relative path: {path_text!r}")
    if any(part.split(".")[0].upper() in WINDOWS_DEVICE_NAMES for part in path.parts):
        raise ContractError(f"Windows device name is forbidden: {path_text!r}")
    if any(part.startswith(".") for part in path.parts):
        raise ContractError(f"hidden path component is forbidden: {path_text!r}")
    if any(path_text.startswith(root) for root in DENIED_ROOTS):
        raise ContractError(f"denied benchmark input path: {path_text}")
    return path


def _resolved_repository_file(relative_path: str, allowed_roots: tuple[str, ...]) -> Path:
    validate_relative_path(relative_path)
    if not any(relative_path.startswith(prefix) for prefix in allowed_roots):
        raise ContractError(f"path is outside its trusted allowlist: {relative_path}")
    root = ROOT.resolve(strict=True)
    path = ROOT.joinpath(*PurePosixPath(relative_path).parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ContractError(f"path escapes the repository or is missing: {relative_path}") from exc
    current = ROOT
    for part in PurePosixPath(relative_path).parts:
        current = current / part
        is_junction = getattr(current, "is_junction", lambda: False)()
        if current.is_symlink() or is_junction:
            raise ContractError(f"symlink or junction is forbidden: {relative_path}")
    if not resolved.is_file():
        raise ContractError(f"missing file: {relative_path}")
    return resolved


def read_bytes(relative_path: str, allowed_roots: tuple[str, ...] = STATIC_SOURCE_ROOTS) -> bytes:
    return _resolved_repository_file(relative_path, allowed_roots).read_bytes()


def load_json(relative_path: str) -> dict[str, Any]:
    try:
        loaded = json.loads(read_text(relative_path))
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON: {relative_path}") from exc
    if not isinstance(loaded, dict):
        raise ContractError(f"top-level JSON object required: {relative_path}")
    return loaded


def media_type(path: str) -> str:
    return {
        ".json": "application/json",
        ".md": "text/markdown",
        ".py": "text/x-python",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".lock": "text/plain",
    }.get(PurePosixPath(path).suffix, "application/octet-stream")


def _serialize_role(role: str, components: list[dict[str, str]]) -> bytes:
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


def _load_pack(pack_id: str) -> tuple[dict[str, Any], bytes, str, str]:
    manifest = load_json("prompts/prompt_manifest.json")
    if manifest.get("status") != "draft":
        raise ContractError("only the reviewed draft-v1 prompt library is supported")
    matches = [item for item in manifest.get("packs", []) if item.get("pack_id") == pack_id]
    if len(matches) != 1:
        raise ContractError(f"unknown or ambiguous pack ID: {pack_id}")
    pack = matches[0]
    components = pack.get("components")
    expected_components = _expected_pack_components(pack_id)
    if not isinstance(components, list) or components != expected_components:
        raise ContractError(f"pack components differ from the runtime allowlist: {pack_id}")
    registrations = manifest.get("artifacts", [])
    for component in components:
        path = component["path"]
        matches = [
            item for item in registrations
            if item.get("path") == path and item.get("purpose") in {"prompt", "schema"}
        ]
        content = read_bytes(path)
        if (
            len(matches) != 1
            or matches[0].get("byte_length") != len(content)
            or matches[0].get("sha256") != sha256(content)
        ):
            raise ContractError(f"pack component is not integrity-registered: {path}")
    try:
        system = _serialize_role("system", [item for item in components if item["role"] == "system"])
        user = _serialize_role("user", [item for item in components if item["role"] == "user"])
    except (KeyError, TypeError) as exc:
        raise ContractError(f"invalid component definition: {pack_id}") from exc
    serialized = b"CPACK/1\n" + length_prefixed("SYSTEM", system) + length_prefixed("USER", user)
    actual_hash = sha256(serialized)
    if actual_hash != pack.get("pack_sha256"):
        raise ContractError(f"static pack hash mismatch: {pack_id}")
    return pack, serialized, system.decode("utf-8"), user.decode("utf-8")


def _load_approved_artifacts(
    input_manifest_path: str, expected_pack_id: str
) -> tuple[dict[str, Any], bytes, list[tuple[dict[str, Any], bytes]]]:
    expected_pack_type = "report" if expected_pack_id == "report-v1" else "codegen"
    trusted_root = INPUT_ROOT_BY_PACK_TYPE[expected_pack_type]
    manifest_bytes = read_bytes(input_manifest_path, (trusted_root,))
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid input manifest JSON: {input_manifest_path}") from exc
    _validate_input_manifest_contract(manifest, expected_pack_id, expected_pack_type, input_manifest_path)
    if manifest_bytes != canonical_json_document(manifest):
        raise ContractError(f"input manifest must be canonical sorted-key JSON: {input_manifest_path}")
    if manifest["schema_version"] != "1.0.0" or manifest["pack_id"] != expected_pack_id:
        raise ContractError("input manifest does not match the requested pack")
    if tuple(manifest["forbidden_roots"]) != DENIED_ROOTS:
        raise ContractError("input manifest forbidden roots differ from benchmark contract")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ContractError("at least one approved input artifact is required")

    allowed_source_kinds = (
        {"starter_repository", "synthetic_fixture", "public_interface", "dependency_lock"}
        if manifest["pack_type"] == "codegen"
        else {"evidence_projection"}
    )
    registered: list[tuple[dict[str, Any], bytes]] = []
    seen: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ContractError("input artifact must be an object")
        required_artifact = {
            "path",
            "media_type",
            "byte_length",
            "sha256",
            "source_kind",
            "approved_for_model",
        }
        expected_artifact_fields = (
            required_artifact | {"projection"}
            if manifest["pack_type"] == "report"
            else required_artifact
        )
        if set(artifact) != expected_artifact_fields:
            raise ContractError(f"invalid artifact fields: {artifact.get('path', '<unknown>')}")
        path = artifact["path"]
        validate_relative_path(path)
        if path in seen:
            raise ContractError(f"duplicate input artifact: {path}")
        seen.add(path)
        if artifact["source_kind"] not in allowed_source_kinds or artifact["approved_for_model"] is not True:
            raise ContractError(f"artifact is not approved for this benchmark input: {path}")
        if manifest["pack_type"] == "report" and artifact["projection"] not in {
            "canonical_json",
            "deterministic_csv",
            "deterministic_text",
        }:
            raise ContractError(f"unsupported report projection: {path}")
        if artifact["media_type"] != media_type(path):
            raise ContractError(f"unexpected media type: {path}")
        validate_approved_artifact_path(manifest["pack_type"], path, expected_pack_id)
        content = read_bytes(path, (trusted_root,))
        if artifact["byte_length"] != len(content) or artifact["sha256"] != sha256(content):
            raise ContractError(f"input artifact integrity mismatch: {path}")
        _validate_model_visible_artifact(artifact, content)
        registered.append((artifact, content))
    return manifest, manifest_bytes, registered


def _validate_input_manifest_contract(
    manifest: dict[str, Any], expected_pack_id: str, expected_pack_type: str, path: str
) -> None:
    common = {"schema_version", "pack_id", "pack_type", "artifacts", "forbidden_roots"}
    expected_fields = common | ({"study_id"} if expected_pack_type == "report" else set())
    if set(manifest) != expected_fields:
        raise ContractError(f"invalid top-level input-manifest fields: {path}")
    if manifest.get("schema_version") != "1.0.0" or manifest.get("pack_id") != expected_pack_id:
        raise ContractError("input manifest does not match the requested pack")
    if manifest.get("pack_type") != expected_pack_type:
        raise ContractError("input manifest pack type does not match pack ID")
    if expected_pack_type == "report" and not isinstance(manifest.get("study_id"), str):
        raise ContractError("report input manifest requires a study ID")


def validate_approved_artifact_path(pack_type: str, path: str, pack_id: str | None = None) -> None:
    """Enforce the hard model-visible root allowlist, independent of manifest labels."""
    validate_relative_path(path)
    trusted_root = INPUT_ROOT_BY_PACK_TYPE.get(pack_type)
    if trusted_root is None or not path.startswith(trusted_root):
        raise ContractError(f"artifact path is outside the {pack_type!r} input allowlist: {path}")
    if pack_id is not None and path not in APPROVED_ARTIFACTS_BY_PACK.get(pack_id, set()):
        raise ContractError(f"artifact path is not registered for {pack_id}: {path}")


def _validate_model_visible_artifact(artifact: dict[str, Any], content: bytes) -> None:
    media = artifact["media_type"]
    projection = artifact.get("projection")
    if projection == "canonical_json" and media != "application/json":
        raise ContractError(f"canonical_json projection must use JSON media type: {artifact['path']}")
    if projection == "deterministic_csv" and media != "text/csv":
        raise ContractError(f"deterministic_csv projection must use CSV media type: {artifact['path']}")
    if media not in {"application/json", "text/markdown", "text/x-python", "text/plain", "text/csv"}:
        raise ContractError(f"binary model-visible artifact is forbidden: {artifact['path']}")
    if content.startswith(b"\xef\xbb\xbf") or b"\r" in content or not content.endswith(b"\n"):
        raise ContractError(f"model-visible artifact must be UTF-8/LF with terminal newline: {artifact['path']}")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"model-visible artifact is not UTF-8: {artifact['path']}") from exc
    if text != unicodedata.normalize("NFC", text):
        raise ContractError(f"model-visible artifact is not Unicode NFC: {artifact['path']}")
    if media == "application/json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid model-visible JSON: {artifact['path']}") from exc
        if content != canonical_json_document(parsed):
            raise ContractError(f"model-visible JSON is not canonical: {artifact['path']}")
    if media == "text/csv":
        try:
            list(csv.reader(io.StringIO(text, newline=""), strict=True))
        except csv.Error as exc:
            raise ContractError(f"invalid deterministic CSV: {artifact['path']}") from exc


def _serialize_input_bundle(manifest_bytes: bytes, artifacts: list[tuple[dict[str, Any], bytes]]) -> bytes:
    result = bytearray(b"BENCHMARK-INPUT-BUNDLE/1\n")
    result.extend(length_prefixed("INPUT_MANIFEST", manifest_bytes))
    for index, (artifact, content) in enumerate(artifacts, start=1):
        result.extend(f"ARTIFACT {index}\n".encode("ascii"))
        result.extend(length_prefixed("PATH", artifact["path"].encode("utf-8")))
        result.extend(length_prefixed("MEDIA_TYPE", artifact["media_type"].encode("ascii")))
        result.extend(length_prefixed("SOURCE_KIND", artifact["source_kind"].encode("ascii")))
        result.extend(length_prefixed("SHA256", artifact["sha256"].encode("ascii")))
        result.extend(length_prefixed("CONTENT", content))
    return bytes(result)


def render_prompt(pack_id: str, input_manifest_path: str) -> RenderedPrompt:
    """Return the provider-neutral prompt texts for one fully verified run input."""
    pack, _serialized, system, base_user = _load_pack(pack_id)
    _manifest, manifest_bytes, artifacts = _load_approved_artifacts(input_manifest_path, pack_id)
    input_bundle = _serialize_input_bundle(manifest_bytes, artifacts)
    user_bytes = base_user.encode("utf-8") + length_prefixed("INPUT_BUNDLE", input_bundle)
    user = user_bytes.decode("utf-8")
    visible = length_prefixed("SYSTEM", system.encode("utf-8")) + length_prefixed("USER", user_bytes)
    return RenderedPrompt(
        pack_id=pack_id,
        static_pack_sha256=pack["pack_sha256"],
        input_manifest_sha256=sha256(manifest_bytes),
        input_bundle_sha256=sha256(input_bundle),
        system=system,
        user=user,
        model_visible_sha256=sha256(visible),
    )
