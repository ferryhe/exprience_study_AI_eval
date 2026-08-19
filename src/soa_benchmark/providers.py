"""Provider envelopes that preserve the same canonical model-visible bytes."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from .canonical import ContractError, RenderedPrompt, length_prefixed, read_text, sha256


class ProviderError(RuntimeError):
    """Raised for invalid provider configuration or an unsupported route."""


EXPECTED_ROUTES = {
    "openai": ("responses", "https://api.openai.com/v1", "/responses", "OPENAI_API_KEY"),
    "anthropic": ("messages", "https://api.anthropic.com/v1", "/messages", "ANTHROPIC_API_KEY"),
    "minimax": (
        "messages",
        "https://api.minimaxi.com/anthropic",
        "/v1/messages",
        "MINIMAX_API_KEY",
    ),
    "kimi": (
        "openai_chat_completions_compatible",
        "https://api.moonshot.ai/v1",
        "/chat/completions",
        "MOONSHOT_API_KEY",
    ),
    "deepseek": (
        "openai_chat_completions_compatible",
        "https://api.deepseek.com",
        "/chat/completions",
        "DEEPSEEK_API_KEY",
    ),
}


@dataclass(frozen=True)
class ProviderConfig:
    path: str
    data: dict[str, Any]
    sha256: str

    @property
    def provider(self) -> str:
        return self.data["provider"]

    @property
    def alias(self) -> str:
        return self.data["benchmark_alias"]


def load_provider_config(relative_path: str) -> ProviderConfig:
    try:
        text = read_text(relative_path)
        data = json.loads(text)
    except (json.JSONDecodeError, ContractError) as exc:
        raise ProviderError(f"invalid provider config: {relative_path}") from exc
    try:
        prompt_manifest = json.loads(read_text("prompts/prompt_manifest.json"))
        registrations = [
            item for item in prompt_manifest.get("artifacts", [])
            if item.get("path") == relative_path and item.get("purpose") == "provider_config"
        ]
    except (json.JSONDecodeError, ContractError) as exc:
        raise ProviderError("invalid prompt-manifest provider registration") from exc
    encoded = text.encode("utf-8")
    if len(registrations) != 1 or registrations[0].get("byte_length") != len(encoded) or registrations[0].get("sha256") != sha256(encoded):
        raise ProviderError(f"provider config is not integrity-registered: {relative_path}")
    required = {
        "benchmark_alias",
        "configuration_state",
        "provider",
        "api_style",
        "base_url",
        "endpoint",
        "api_key_env",
        "requested_model_id",
        "max_output_tokens",
        "wall_clock_timeout_seconds",
        "transport_retry_statuses",
        "transport_retry_errors",
        "max_transport_attempts",
        "service_tier",
    }
    missing = required - set(data)
    if missing:
        raise ProviderError(f"provider config missing fields: {sorted(missing)}")
    if data["provider"] not in EXPECTED_ROUTES:
        raise ProviderError(f"unsupported provider: {data['provider']}")
    actual_route = (data["api_style"], data["base_url"], data["endpoint"], data["api_key_env"])
    if actual_route != EXPECTED_ROUTES[data["provider"]]:
        raise ProviderError(f"provider route is not allowlisted: {data['provider']}")
    if not isinstance(data["benchmark_alias"], str) or not data["benchmark_alias"]:
        raise ProviderError("benchmark alias is invalid")
    if not isinstance(data["requested_model_id"], str) or not data["requested_model_id"]:
        raise ProviderError("requested model ID is invalid")
    expected_tier = "default" if data["provider"] == "openai" else "standard"
    if data["service_tier"] != expected_tier:
        raise ProviderError(f"unexpected service tier for {data['provider']}")
    state = data["configuration_state"]
    if state == "pre_probe":
        if (
            data.get("effective_model_id") is not None
            or data.get("effective_model_reason_code") != "not_probed"
            or data.get("version_semantics") != "resolve_at_pilot_freeze"
        ):
            raise ProviderError("pre-probe model state is internally inconsistent")
    elif state == "frozen":
        if (
            not isinstance(data.get("effective_model_id"), str)
            or not data["effective_model_id"]
            or data.get("effective_model_reason_code") != "capability_probe_confirmed"
            or data.get("version_semantics") != "pinned_exact"
            or not isinstance(data.get("capability_probe_date"), str)
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["capability_probe_date"]) is None
        ):
            raise ProviderError("frozen model state is internally inconsistent")
    else:
        raise ProviderError("configuration_state must be pre_probe or frozen")
    if not isinstance(data["max_transport_attempts"], int) or not 1 <= data["max_transport_attempts"] <= 5:
        raise ProviderError("max_transport_attempts must be between 1 and 5")
    if not isinstance(data["wall_clock_timeout_seconds"], (int, float)) or not 1 <= data["wall_clock_timeout_seconds"] <= 1800:
        raise ProviderError("wall_clock_timeout_seconds must be between 1 and 1800")
    if not isinstance(data["transport_retry_statuses"], list) or not all(
        isinstance(item, int) and item in {408, 409, 429, 500, 502, 503, 504}
        for item in data["transport_retry_statuses"]
    ):
        raise ProviderError("transport_retry_statuses contains an unsupported status")
    if not isinstance(data["transport_retry_errors"], list) or not all(
        item in {"timeout", "connection_reset", "remote_disconnected"}
        for item in data["transport_retry_errors"]
    ):
        raise ProviderError("transport_retry_errors contains an unsupported failure class")
    return ProviderConfig(relative_path, data, sha256(encoded))


def model_visible_hash_from_payload(provider: str, payload: dict[str, Any]) -> str:
    if provider == "openai":
        system = payload["input"][0]["content"][0]["text"]
        user = payload["input"][1]["content"][0]["text"]
    elif provider in {"anthropic", "minimax"}:
        system = payload["system"]
        user = payload["messages"][0]["content"]
    else:
        system = payload["messages"][0]["content"]
        user = payload["messages"][1]["content"]
    visible = length_prefixed("SYSTEM", system.encode("utf-8")) + length_prefixed("USER", user.encode("utf-8"))
    return sha256(visible)


def _reasoning_payload(config: ProviderConfig) -> dict[str, Any]:
    settings = config.data.get("native_reasoning_settings")
    if settings is None:
        return {}
    if not isinstance(settings, dict):
        raise ProviderError("native_reasoning_settings must be null or an object")
    if config.provider == "openai":
        return {"reasoning": settings}
    if config.provider == "anthropic":
        return {"output_config": settings}
    if config.provider == "minimax":
        if settings not in ({"type": "disabled"}, {"type": "adaptive"}):
            raise ProviderError("invalid MiniMax thinking-mode mapping")
        return {"thinking": settings}
    if config.provider == "deepseek":
        if settings.get("thinking") != {"type": "enabled"} or settings.get("reasoning_effort") != "high":
            raise ProviderError("invalid DeepSeek thinking-mode mapping")
        return {
            "thinking": settings["thinking"],
            "reasoning_effort": settings["reasoning_effort"],
        }
    return {}


def build_payload(config: ProviderConfig, prompt: RenderedPrompt) -> dict[str, Any]:
    """Build one provider request without adding provider-specific prompt text."""
    if config.provider == "openai":
        payload: dict[str, Any] = {
            "model": config.data["requested_model_id"],
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": prompt.system}]},
                {"role": "user", "content": [{"type": "input_text", "text": prompt.user}]},
            ],
            "max_output_tokens": config.data["max_output_tokens"],
            "store": False,
            "service_tier": config.data["service_tier"],
        }
    elif config.provider in {"anthropic", "minimax"}:
        payload = {
            "model": config.data["requested_model_id"],
            "max_tokens": config.data["max_output_tokens"],
            "system": prompt.system,
            "messages": [{"role": "user", "content": prompt.user}],
        }
        if config.provider == "minimax":
            payload["service_tier"] = config.data["service_tier"]
    else:
        payload = {
            "model": config.data["requested_model_id"],
            "max_tokens": config.data["max_output_tokens"],
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
        }
    payload.update(_reasoning_payload(config))
    visible_hash = model_visible_hash_from_payload(config.provider, payload)
    if visible_hash != prompt.model_visible_sha256:
        raise ProviderError(f"provider envelope changed model-visible bytes: {config.alias}")
    return payload


def endpoint_url(config: ProviderConfig) -> str:
    return config.data["base_url"].rstrip("/") + "/" + config.data["endpoint"].lstrip("/")


def request_headers(config: ProviderConfig, api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": "soa-experience-ai-eval/0.1"}
    if config.provider in {"anthropic", "minimax"}:
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def extract_text(config: ProviderConfig, response: dict[str, Any]) -> str:
    if config.provider == "openai":
        if isinstance(response.get("output_text"), str):
            return response["output_text"]
        parts: list[str] = []
        outputs = response.get("output", [])
        if not isinstance(outputs, list):
            raise ProviderError(f"invalid output collection in {config.alias} response")
        for output in outputs:
            if not isinstance(output, dict) or not isinstance(output.get("content", []), list):
                continue
            for content in output.get("content", []):
                if not isinstance(content, dict):
                    continue
                if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                    parts.append(content["text"])
        if parts:
            return "".join(parts)
    elif config.provider in {"anthropic", "minimax"}:
        content = response.get("content", [])
        if not isinstance(content, list):
            raise ProviderError(f"invalid content collection in {config.alias} response")
        parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if parts and all(isinstance(part, str) for part in parts):
            return "".join(parts)
    else:
        choices = response.get("choices", [])
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message", {})
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                return content
    raise ProviderError(f"no text output found in {config.alias} response")


def _token(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usage_with_integrity(
    values: dict[str, int | None], usage_present: bool
) -> dict[str, int | str | bool | None]:
    failure: str | None = None
    if not usage_present:
        failure = "usage_missing"
    billable = (
        values["uncached_input_tokens"],
        values["cache_read_input_tokens"],
        values["cache_write_input_tokens"],
        values["output_tokens"],
    )
    if failure is None and any(value is None for value in billable):
        failure = "billable_usage_incomplete"
    input_tokens = values["input_tokens"]
    if failure is None and input_tokens is None:
        failure = "input_tokens_missing"
    if failure is None and input_tokens != sum(value for value in billable[:3] if value is not None):
        failure = "input_bucket_sum_mismatch"
    output_tokens = values["output_tokens"]
    total_tokens = values["total_tokens"]
    if (
        failure is None
        and total_tokens is not None
        and input_tokens is not None
        and output_tokens is not None
        and total_tokens != input_tokens + output_tokens
    ):
        failure = "total_token_sum_mismatch"
    reasoning_tokens = values["reasoning_tokens"]
    if (
        failure is None
        and reasoning_tokens is not None
        and output_tokens is not None
        and reasoning_tokens > output_tokens
    ):
        failure = "reasoning_exceeds_output"
    return {
        **values,
        "integrity_valid": failure is None,
        "integrity_failure_code": failure,
    }


def normalize_usage(config: ProviderConfig, response: dict[str, Any]) -> dict[str, int | str | bool | None]:
    """Map provider telemetry to mutually exclusive billable token categories."""
    raw_usage = response.get("usage")
    usage = raw_usage or {}
    if not isinstance(usage, dict):
        usage = {}
    if config.provider == "openai":
        input_details = usage.get("input_tokens_details") or {}
        output_details = usage.get("output_tokens_details") or {}
        if not isinstance(input_details, dict):
            input_details = {}
        if not isinstance(output_details, dict):
            output_details = {}
        input_tokens = _token(usage.get("input_tokens"))
        cache_read = _token(input_details.get("cached_tokens")) or 0
        cache_write = _token(input_details.get("cache_write_tokens"))
        if cache_write is None:
            cache_write = _token(usage.get("cache_write_tokens")) or 0
        uncached = None if input_tokens is None else max(input_tokens - cache_read - cache_write, 0)
        output_tokens = _token(usage.get("output_tokens"))
        total = _token(usage.get("total_tokens"))
        if total is None and input_tokens is not None and output_tokens is not None:
            total = input_tokens + output_tokens
        reasoning = _token(output_details.get("reasoning_tokens"))
    elif config.provider in {"anthropic", "minimax"}:
        uncached = _token(usage.get("input_tokens"))
        cache_read = _token(usage.get("cache_read_input_tokens")) or 0
        cache_write = _token(usage.get("cache_creation_input_tokens")) or 0
        input_tokens = None if uncached is None else uncached + cache_read + cache_write
        output_tokens = _token(usage.get("output_tokens"))
        total = None if input_tokens is None or output_tokens is None else input_tokens + output_tokens
        if config.provider == "minimax":
            output_details = usage.get("output_tokens_details") or {}
            if not isinstance(output_details, dict):
                output_details = {}
            reasoning = _token(output_details.get("thinking_tokens"))
        else:
            reasoning = _token(usage.get("reasoning_tokens"))
    elif config.provider == "deepseek":
        input_tokens = _token(usage.get("prompt_tokens"))
        cache_read = _token(usage.get("prompt_cache_hit_tokens")) or 0
        uncached = _token(usage.get("prompt_cache_miss_tokens"))
        if uncached is None and input_tokens is not None:
            uncached = max(input_tokens - cache_read, 0)
        cache_write = 0
        output_tokens = _token(usage.get("completion_tokens"))
        total = _token(usage.get("total_tokens"))
        details = usage.get("completion_tokens_details") or {}
        if not isinstance(details, dict):
            details = {}
        reasoning = _token(details.get("reasoning_tokens"))
        if total is None and input_tokens is not None and output_tokens is not None:
            total = input_tokens + output_tokens
    else:
        input_tokens = _token(usage.get("prompt_tokens"))
        input_details = usage.get("prompt_tokens_details") or {}
        if not isinstance(input_details, dict):
            input_details = {}
        cache_read = _token(input_details.get("cached_tokens")) or 0
        cache_write = _token(input_details.get("cache_write_tokens")) or 0
        uncached = None if input_tokens is None else max(input_tokens - cache_read - cache_write, 0)
        output_tokens = _token(usage.get("completion_tokens"))
        total = _token(usage.get("total_tokens"))
        details = usage.get("completion_tokens_details") or {}
        if not isinstance(details, dict):
            details = {}
        reasoning = _token(details.get("reasoning_tokens"))
        if total is None and input_tokens is not None and output_tokens is not None:
            total = input_tokens + output_tokens
    return _usage_with_integrity({
        "input_tokens": input_tokens,
        "uncached_input_tokens": uncached,
        "cache_read_input_tokens": cache_read,
        "cache_write_input_tokens": cache_write,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
    }, isinstance(raw_usage, dict) and bool(raw_usage))


def returned_model_id(config: ProviderConfig, response: dict[str, Any]) -> str | None:
    value = response.get("model")
    return value if isinstance(value, str) else None


def returned_service_tier(config: ProviderConfig, response: dict[str, Any]) -> str | None:
    if config.provider != "openai":
        return None
    value = response.get("service_tier")
    return value if isinstance(value, str) else None
