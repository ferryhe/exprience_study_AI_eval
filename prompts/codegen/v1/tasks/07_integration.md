# C7 — Evidence-bundle integration

## Objective

Integrate validated manifests, populations, metrics, exhibits, model diagnostics, exceptions, and limitations into a deterministic evidence bundle.

## Allowed paths

- `src/soa_experience/evidence/models.py`
- `src/soa_experience/evidence/build.py`
- `src/soa_experience/evidence/validate.py`

## Required behavior

- Build the declared source, run, validation, exception, reconciliation, population, metric, citation, model, and limitation artifacts.
- Include stable evidence IDs with definition, locator, value metadata, source/run hashes, rounding rule, and allowed narrative use.
- Reject dangling citations, duplicate IDs, incompatible unit/population/period/basis metadata, missing required artifacts, unreconciled released values, and release-blocking validation failures.
- Use stable ordering, canonical JSON rules, explicit timestamps supplied by configuration, and deterministic content hashes.
- Produce a model-visible report projection containing only approved aggregate evidence and no production TSV row, hidden test, gold output, secret, or executable instruction.
- Validate the bundle and projection against supplied schemas without rendering report prose or calling a model API.

## Public interface

Implement the starter repository's declared `build_evidence` and evidence-validation interfaces without changing their signatures.

## Evaluator checks

The evaluator will check complete assembly, cross-artifact references, duplicate/dangling IDs, metadata compatibility, release blocking, canonical hashes, forbidden-content exclusion, injection boundary labels, and byte-identical output on clean replay.
