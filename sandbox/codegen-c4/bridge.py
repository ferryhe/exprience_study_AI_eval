"""Trusted JSON bridge between the host evaluator and an untrusted C4 subject."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
import io
import json
import sys


MAX_INPUT_BYTES = 262_144
MAX_SUBJECT_OUTPUT_BYTES = 65_536


class _LimitedCapture(io.TextIOBase):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.size = 0

    def write(self, value: str) -> int:
        encoded_size = len(value.encode("utf-8"))
        self.size += encoded_size
        if self.size > self.limit:
            raise RuntimeError("subject output limit exceeded")
        return len(value)


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    sys.stdout.write("\n")


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("evaluation request is too large")
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError("evaluation request must be an object")

        capture = _LimitedCapture(MAX_SUBJECT_OUTPUT_BYTES)
        with redirect_stdout(capture), redirect_stderr(capture):
            import polars as pl

            from soa_experience.calculations.actual_to_expected import (
                compute_grouped_actual_to_expected,
            )
            from soa_experience.calculations.interfaces import ExperienceInput, GroupingRequest

            experience_input = ExperienceInput(
                population_id=str(request["population_id"]),
                period=str(request["period"]),
                rows=pl.DataFrame(request["rows"]).lazy(),
            )
            grouping = GroupingRequest(tuple(str(value) for value in request["dimensions"]))
            results = compute_grouped_actual_to_expected(experience_input, grouping)
            serialized = [asdict(result) for result in results]

        _emit(
            {
                "ok": True,
                "results": serialized,
                "subject_output_bytes": capture.size,
            }
        )
        return 0
    except Exception as exc:
        _emit(
            {
                "ok": False,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc)[:1000],
                },
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
