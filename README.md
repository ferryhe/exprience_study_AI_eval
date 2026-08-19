# SOA Experience Study AI Evaluation

This repository is the Objective 2 subproject for building and evaluating a
life-insurance experience-study data-to-report workflow.

The intended product takes the supplied SOA ILEC 2012-2019 experience data and
turns it into:

- a deterministic actuarial evidence bundle;
- an SOA-style report in canonical JSON, HTML, and PDF;
- a Tableau-like tabular web experience for filtering, exhibits, charts, and
  downloads;
- four comparable AI-generated report outputs using the same prompt, same input
  package, same output contract, and direct API calls; and
- a benchmark scorecard covering quality, correctness, latency, token usage,
  API cost, failures, and human repair effort.

AI-generated narrative is never the source of truth for calculations. The
deterministic data package, validation rules, exposure logic, actual-to-expected
calculations, exhibits, model diagnostics, and evidence IDs remain authoritative.

## Project Shape

The project has two connected layers.

1. The production study layer will register the SOA source files, validate the
   data, build canonical Parquet and exhibit tables, calculate A/E results, fit
   approved explanatory models, assemble the evidence bundle, render the
   reference report, and serve the web application.
2. The benchmark layer tests AI providers against frozen prompt packs and
   frozen evidence or code fixtures. Provider adapters may change only the API
   envelope. They must not change the model-visible prompt bytes.

The current repository primarily contains the benchmark preparation layer:
prompt library, provider configuration stubs, schemas, synthetic fixtures,
offline validation, and the direct-API runner skeleton.

For code-generation benchmark tasks, model output will be evaluated in an isolated
sandbox before it can influence production calculation code. The sandbox must
disable primary-lane network access, use a dependency allowlist and frozen
lockfile, isolate secrets and evaluator assets, enforce resource and time
limits, run static/security scans, test prompt-injection and data-exfiltration
cases, and require tests plus human approval before promotion.

The sandbox stores the exact extracted submission, labels API success as
`response_contract_valid`, applies a deterministic static policy gate, and
materializes only statically approved files below `runs/`. A frozen,
digest-pinned Docker image then runs public, external-black-box actuarial,
prompt-injection, exfiltration-isolation, and deterministic replay gates without
mounting the repository or secrets. Machine success means
`ready_for_human_review`; it never makes code automatically promotion-eligible.

## Target Provider Routes

The planned direct-API comparison routes are:

- `gpt-5.6-sol`
- `claude-opus-5`
- `kimi-k3`
- `deepseek-v4-pro`

These aliases are benchmark labels. The actual returned or effective model IDs
must be confirmed by capability probes before any paid pilot or confirmatory
matrix run.

## Repository Layout

```text
benchmark_contracts/   JSON Schemas for run, probe, batch, and pricing manifests
configs/providers/     Public provider envelope settings, no secrets
configs/sandbox/       Public code-generation isolation and static-scan policy
configs/pricing/       Registered live pricing snapshots, currently gated
data/                  Local SOA source data, Git-ignored
docs/                  Delivery plan and benchmark readiness notes
fixtures/              Small synthetic smoke fixtures and evaluator-only checks
prompts/               Frozen provider-neutral prompt sources and manifest
runs/                  Local raw API responses and run manifests, Git-ignored
schemas/               Prompt, report, and code-submission schemas
scripts/               Validation and benchmark CLI entry points
src/soa_benchmark/     Prompt, provider, billing, runner, and sandbox gates
tests/                 Offline safety and contract tests
```

## Local Data Boundary

Large SOA source files live under `data/` and are intentionally not committed.
The report target and Tableau-like target are reference products, not files to
copy verbatim. The project goal is analytical and functional equivalence:
validated calculations, comparable exhibits, clear limitations, and reproducible
publication artifacts.

Raw production TSV rows, secrets, hidden tests, gold outputs, historical outputs,
and evaluator-only files must not become model-visible prompt artifacts.

## Secrets

API keys belong in `.env.local`, which is Git-ignored. Public provider config
files contain only route metadata such as base URL, endpoint family, key
environment-variable name, retry policy, and requested settings.

Do not print or commit `.env.local`.

Expected key variable names are documented in `.env.example`.

## Offline Verification

Install the pinned benchmark dependencies:

```text
python -m pip install -r requirements-benchmark.lock
```

Run the offline checks:

```text
python scripts/validate_prompt_library.py
python scripts/validate_benchmark_readiness.py
python -m unittest discover -s tests -v
python scripts/run_benchmark.py preflight --pack-id codegen-c4-v1 --input-manifest fixtures/codegen/c4/input_manifest.json
python scripts/run_benchmark.py preflight --pack-id report-v1 --input-manifest fixtures/report/small_evidence/input_manifest.json
```

These commands do not require API keys and do not send provider requests.

Build and verify the frozen C4 sandbox image:

```text
python scripts/build_codegen_sandbox.py
```

After an API run has produced a code submission, invoke the sandbox gate with:

```text
python scripts/run_benchmark.py evaluate-codegen --run-manifest runs/<run-id>/run_manifest.json
```

The command never falls back to host execution. A missing Docker backend or
frozen image returns a blocked machine disposition.

## Live Benchmark Gate

Paid API runs are intentionally blocked until all selected provider routes pass
these gates:

1. Run a low-cost capability probe for each route.
2. Record the returned effective model ID and accepted reasoning/output
   settings.
3. Change the provider config from `pre_probe` to `frozen`.
4. Update the provider config hash registration in `prompts/prompt_manifest.json`.
5. Add an official dated pricing snapshot under `configs/pricing/` and register
   it in `configs/pricing/pricing_manifest.json`.
6. Run one smoke request per route before starting the comparison matrix.

Example probe shape:

```text
python scripts/run_benchmark.py probe --provider-config configs/providers/openai.json
```

Example paid pilot shape after freeze and pricing registration:

```text
python scripts/run_benchmark.py run --pack-id codegen-c4-v1 --input-manifest fixtures/codegen/c4/input_manifest.json --provider-config configs/providers/openai.json --pricing-snapshot configs/pricing/pilot-YYYY-MM-DD.json --run-stage pilot
```

## Main References

- Benchmark operation manual:
  `docs/benchmark_operation_manual.md`
- Final delivery specification:
  `docs/experience_study_implementation_and_benchmark_plan.md`
- Prompt-library design:
  `docs/prompt_library_build_plan.md`
- Benchmark execution readiness:
  `docs/benchmark_execution_readiness.md`
- Prompt pack overview:
  `prompts/README.md`
- Pricing snapshot rules:
  `configs/pricing/README.md`

## Current Status

The offline benchmark harness, synthetic fixtures, extracted-submission handoff,
and frozen Docker C4 sandbox are testable. Formal API comparison still requires
live capability probes, frozen effective model IDs, and official pricing
snapshots. Generated code that passes the machine gates still requires separate
human code review and actuarial approval before promotion.
