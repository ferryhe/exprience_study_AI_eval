# Direct-API Benchmark Execution Readiness

**Status:** The offline harness and synthetic fixtures are testable. Paid benchmark runs are intentionally gated until each route has passed a capability probe, its effective model ID has been frozen, and a matching official pricing snapshot has been registered. The configured Kimi K3, Claude Opus 5, and DeepSeek V4 Pro identifiers remain capability-probe candidates rather than verified availability claims.

## Implemented contract

- `.env.local` is Git-ignored. When a key exists both in the process environment and the selected env file, the env-file value wins; manifests record only `env_file` or `process_environment`, never the value.
- Model-visible artifacts are restricted to exact per-pack registrations below `fixtures/codegen/` or `fixtures/report/`. Hidden paths, data/gold/output roots, unregistered evaluator answers, repository escapes, symlinks, and junctions are rejected.
- Model-visible text must be UTF-8 without BOM, LF-only, NFC-normalized, and newline-terminated. Model-visible JSON and input manifests must use sorted-key canonical formatting.
- All four provider envelopes preserve the same system and user bytes. Anthropic receives `output_config.effort`; DeepSeek receives object-form thinking mode and `reasoning_effort`; OpenAI fixes `service_tier=default`. These request capabilities still require live probes.
- Credential-bearing HTTP requests never follow redirects. The initial provider host, endpoint, API-key variable, and provider-config hash are all runtime allowlisted.
- Every HTTP response, including retryable errors, receives its own local raw file and SHA-256. The attempt ledger records timing, status, request ID, failure class, retry decision, and backoff. Only configured status codes and normalized transport classes are retried; model-output failures are not retried.
- Usage is normalized into total input, uncached input, cache-read input, cache-write input, output, reasoning, and total tokens for every attempt. Token identities are checked before cost can be complete. If any retry lacks telemetry, aggregate token values remain `null` while known subtotals and missing-attempt counts are retained. Cost uses Decimal arithmetic and a versioned price snapshot; monetary values are decimal strings. These are reproducible list-price estimates and should be reconciled to provider billing exports for final financial reporting.
- Run replay identity records Git commit, dirty state, status hash, Python/jsonschema versions, and a hash of the actual runner/config/schema/contract sources. Confirmatory runs require a clean tree; pilot runs retain the dirty-state evidence.
- Matrix order rotates by repetition and records execution order. Multi-provider repetitions must be a multiple of the provider count, so each route occupies every position equally. Cache lanes are explicitly observational; the harness does not claim control of provider-side cache state.
- Raw responses are local and Git-ignored, not encrypted by this repository. Apply the project's access control and retention policy to `runs/`; delete retained responses only under that approved policy.

## Offline acceptance commands

```text
python -m pip install -r requirements-benchmark.lock
python scripts/validate_prompt_library.py
python scripts/validate_benchmark_readiness.py
python -m unittest discover -s tests -v
python scripts/run_benchmark.py preflight --pack-id codegen-c4-v1 --input-manifest fixtures/codegen/c4/input_manifest.json
python scripts/run_benchmark.py preflight --pack-id report-v1 --input-manifest fixtures/report/small_evidence/input_manifest.json
```

The included `fixtures/pricing/synthetic_pricing_snapshot.json` contains invented test rates. It must not be supplied to a paid request.

## Capability and pricing gates

1. Run one 64-token-limit capability probe per configured route. A probe is accepted only when a successful response can be extracted as exactly the JSON object `{"ok": true}`. Transport failures still produce a probe record.
2. Record the returned/effective model ID, accepted reasoning controls, actual 64-token probe limit, request ID, finish reason, usage fields, and probe response hash. Confirm the larger production output limit separately before freezing it; the low-cost probe does not prove 32,000-token output support. A probe without a pricing snapshot records cost as unavailable rather than zero.
3. Change the public provider config from `configuration_state=pre_probe` to `frozen`; set the verified `effective_model_id`, `effective_model_reason_code=capability_probe_confirmed`, `version_semantics=pinned_exact`, and `capability_probe_date`. Regenerate that config's byte length and SHA-256 in `prompts/prompt_manifest.json`; both pre-probe and internally consistent frozen configs pass the validator.
4. Create a dated pricing snapshot under `configs/pricing/` using `benchmark_contracts/pricing_snapshot.schema.json`. Every model/service-tier entry needs its own official provider `source_url` and effective timestamp. Register the file's path, byte length, and SHA-256 in `configs/pricing/pricing_manifest.json`. Unsupported cache categories are `null`, not zero. Fixture snapshots are rejected by live run/probe commands.
5. Run one C4 smoke request and one report smoke request per route. Do not start the comparison matrix until all requested routes have credentials, matching frozen prices, and accepted probes.

Example probe (no price is asserted):

```text
python scripts/run_benchmark.py probe --provider-config configs/providers/openai.json
```

Example paid pilot shape after the gates are complete:

```text
python scripts/run_benchmark.py run --pack-id codegen-c4-v1 --input-manifest fixtures/codegen/c4/input_manifest.json --provider-config configs/providers/openai.json --pricing-snapshot configs/pricing/pilot-YYYY-MM-DD.json --run-stage pilot
```

The four-provider matrix defaults to four repetitions. Any requested repetition count must be a multiple of the selected provider count.

## Code-generation sandbox gate

Before code-generation benchmark outputs are executed or considered for the
calculation package, each submission must pass a declared sandbox gate:

- no network access in the primary lane;
- frozen dependency lockfile plus dependency allowlist;
- no mounted secrets, raw production rows, hidden tests, gold outputs, or
  provider credentials;
- fixed wall-clock, CPU, memory, disk, process, file-count, and output-size
  limits;
- static/security scans before execution;
- prompt-injection and data-exfiltration tests with canary detection; and
- public tests, hidden actuarial tests, reproducibility checks, human code
  review, and actuarial approval before promotion into production calculation
  logic.

Sandbox failure is a benchmark outcome and must remain visible in the scorecard.

## Remaining production gates

- The actual challenge starter repository, hidden evaluator, score rubric, reviewer protocol, deterministic JSON-to-HTML/PDF renderer, and production evidence bundle are not supplied by these smoke fixtures.
- TTFT remains unavailable in the primary non-streaming lane. Compare round-trip and total elapsed time there; add a separately declared streaming measurement lane if TTFT is required.
- Freeze the model list, price snapshot, prompt/input hashes, repetitions, cache lanes, time budget, and reviewer acceptance threshold before confirmatory execution.
