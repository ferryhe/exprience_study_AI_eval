# Prompt library

This directory contains the provider-neutral, versioned prompts for the direct-API benchmark. Canonical prompt content is never duplicated in provider configuration.

## Draft v1 packs

- `report-v1`: common system controls, evidence rules, output rules, report task, outline, limitations, style guide, and the model-report schema.
- `codegen-c1-v1` through `codegen-c7-v1`: common controls, shared code instructions, one bounded task, and the code-submission schema.

The ordered components, roles, byte lengths, SHA-256 values, and pack identities are registered in `prompt_manifest.json`. Files listed under `manifest_examples/` illustrate future model-visible input manifests; they are not production evidence or benchmark fixtures.

## Primary comparison rules

The primary lane uses JSON-only instructions plus local schema validation. Provider-native constrained decoding, tools, browsing, retrieval, code execution, and multi-agent features are disabled. Only registered transient HTTP statuses or normalized transport failures may be retried automatically. Invalid JSON, schema-invalid output, and other model-output failures remain scored first-run failures.

Raw production TSV content, hidden tests, gold outputs, reference implementations, secrets, historical outputs, and provider instruction files are never included in a model-visible pack.

Run the offline checks with Python 3.12 and `jsonschema` available:

```text
python scripts/validate_prompt_library.py
```

The direct-API execution baseline, including the synthetic C4 and report smoke fixtures, is documented in `docs/benchmark_execution_readiness.md`. It remains separate from the draft prompt manifest so that execution telemetry and credentials never alter the frozen model-visible prompt sources.
