"""CLI for benchmark preflight and single-provider direct-API runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soa_benchmark.canonical import ContractError, render_prompt  # noqa: E402
from soa_benchmark.billing import PricingError  # noqa: E402
from soa_benchmark.providers import ProviderError  # noqa: E402
from soa_benchmark.runner import (  # noqa: E402
    DEFAULT_PROVIDER_CONFIGS,
    RunnerError,
    capability_probe,
    preflight,
    run_matrix,
    run_once,
)


def workspace_relative(value: str) -> str:
    """Accept Windows CLI paths while passing canonical POSIX paths to the loader."""
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else ROOT / candidate).resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise RunnerError("path must remain inside the repository") from exc


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("preflight", "run", "matrix"):
        command = commands.add_parser(name)
        command.add_argument("--pack-id", required=True)
        command.add_argument("--input-manifest", required=True)
    preflight_command = commands.choices["preflight"]
    preflight_command.add_argument(
        "--provider-config",
        action="append",
        dest="provider_configs",
        help="repeat for a subset; defaults to all four routes",
    )
    run_command = commands.choices["run"]
    run_command.add_argument("--provider-config", required=True)
    run_command.add_argument("--env-file", default=".env.local")
    run_command.add_argument("--output-root", default="runs")
    run_command.add_argument("--pricing-snapshot", required=True)
    run_command.add_argument("--run-id")
    run_command.add_argument("--cache-lane", default="primary_quality_repeatability")
    run_command.add_argument("--run-stage", choices=("pilot", "confirmatory"), default="pilot")
    matrix_command = commands.choices["matrix"]
    matrix_command.add_argument("--provider-config", action="append", dest="provider_configs")
    matrix_command.add_argument("--repetitions", type=int, default=4)
    matrix_command.add_argument("--env-file", default=".env.local")
    matrix_command.add_argument("--output-root", default="runs")
    matrix_command.add_argument("--pricing-snapshot", required=True)
    matrix_command.add_argument("--batch-id")
    matrix_command.add_argument("--cache-lane", default="primary_quality_repeatability")
    matrix_command.add_argument("--run-stage", choices=("pilot", "confirmatory"), default="pilot")
    probe_command = commands.add_parser("probe")
    probe_command.add_argument("--provider-config", required=True)
    probe_command.add_argument("--env-file", default=".env.local")
    probe_command.add_argument("--output-root", default="runs")
    probe_command.add_argument("--probe-id")
    probe_command.add_argument("--pricing-snapshot")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "probe":
            output = capability_probe(
                provider_config_path=workspace_relative(args.provider_config),
                env_file=ROOT / args.env_file,
                output_root=ROOT / args.output_root,
                probe_id=args.probe_id,
                pricing_snapshot_path=(
                    workspace_relative(args.pricing_snapshot) if args.pricing_snapshot else None
                ),
            )
            print(output.relative_to(ROOT).as_posix())
            return 0
        input_manifest = workspace_relative(args.input_manifest)
        prompt = render_prompt(args.pack_id, input_manifest)
        if args.command == "preflight":
            provider_configs = tuple(
                workspace_relative(path)
                for path in (args.provider_configs or DEFAULT_PROVIDER_CONFIGS)
            )
            result = preflight(prompt, provider_configs)
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.command == "matrix":
            provider_configs = tuple(
                workspace_relative(path)
                for path in (args.provider_configs or DEFAULT_PROVIDER_CONFIGS)
            )
            output = run_matrix(
                prompt=prompt,
                provider_config_paths=provider_configs,
                env_file=ROOT / args.env_file,
                output_root=ROOT / args.output_root,
                pricing_snapshot_path=workspace_relative(args.pricing_snapshot),
                repetitions=args.repetitions,
                batch_id=args.batch_id,
                cache_lane=args.cache_lane,
                run_stage=args.run_stage,
            )
            print(output.relative_to(ROOT).as_posix())
            return 0
        manifest = run_once(
            prompt=prompt,
            provider_config_path=workspace_relative(args.provider_config),
            env_file=ROOT / args.env_file,
            output_root=ROOT / args.output_root,
            pricing_snapshot_path=workspace_relative(args.pricing_snapshot),
            run_id=args.run_id,
            cache_lane=args.cache_lane,
            run_stage=args.run_stage,
        )
        print(manifest.relative_to(ROOT).as_posix())
        return 0
    except (ContractError, PricingError, ProviderError, RunnerError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
