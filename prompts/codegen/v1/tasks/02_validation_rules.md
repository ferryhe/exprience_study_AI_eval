# C2 — Deterministic validation rule engine

## Objective

Implement the registered blocking and warning validations for the canonical experience-study dataset.

## Allowed paths

- `src/soa_experience/validation/models.py`
- `src/soa_experience/validation/rules.py`
- `src/soa_experience/validation/runner.py`

## Required behavior

- Produce stable rule IDs, severity, status, observed value, expected constraint, affected-row count, bounded examples, and evidence-ready metadata.
- Validate the exact schema, 45,501,036-row production invariant when that source version is registered, 2012-2019 observation years, and all required 24 source combinations.
- Check finite and nonnegative exposures, actuals, expected values, and moment fields.
- Apply registered categorical domains and explicit null/unknown handling.
- Check issue age, attained age, duration, issue year, observation year, and age-basis relationships using supplied rules.
- Preserve warnings and exceptions; never coerce invalid data silently or downgrade a blocking failure.
- Return results in deterministic rule-ID order and provide an overall release-blocked flag.

## Public interface

Implement the starter repository's declared `validate_study(config)` interface without changing its signature.

## Evaluator checks

The evaluator will use valid and invalid synthetic cells to check severity, null handling, non-finite values, categorical domains, relationship rules, stable ordering, bounded examples, and correct release blocking.
