# C6 — Reproducible Poisson GLM

## Objective

Implement the approved explanatory Poisson GLM without replacing deterministic mortality totals.

## Allowed paths

- `src/soa_experience/models/poisson_glm.py`
- `src/soa_experience/models/diagnostics.py`

## Required behavior

- Model grouped death counts with `log(expected deaths)` as an offset.
- Use the frozen split: train 2012-2017, validate 2018, and test 2019.
- Apply a deterministic design matrix with registered reference levels, missing-value policy, categorical ordering, and seed where applicable.
- Include the supplied methodology-era indicator and support the registered restricted-feature sensitivity.
- Store the formula/specification, feature list, versions, seed, coefficients, standard errors where supported, convergence status, calibration by split, deviance diagnostics, and warnings.
- Reconcile predicted totals to the defined scale and link any narrative candidate finding to a requested deterministic follow-up table.
- Do not claim causality, overwrite deterministic A/E, or silently accept non-convergence or invalid expected values.

## Public interface

Implement the starter repository's approved model specification and diagnostics models. Use only pinned dependencies.

## Evaluator checks

The evaluator will check the offset, time split, deterministic encoding, reproducibility, invalid expected values, non-convergence handling, diagnostics structure, and separation from authoritative totals.
