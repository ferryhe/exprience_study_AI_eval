# C3 — Total, Core, and Modern populations

## Objective

Implement versioned, deterministic population predicates with explicit null and unknown behavior.

## Allowed paths

- `src/soa_experience/populations/definitions.py`
- `src/soa_experience/populations/apply.py`

## Required behavior

- `total_v1`: all valid registered source rows.
- `core_v1`: `Issue_Age >= 18 AND SOA_Post_Lvl_Ind != 'PLT'`.
- `modern_v1`: Core plus `Issue_Year >= 2000`, face amount band 05-11, and `Insurance_Plan != 'Other'`.
- Total retains valid unknown categorical values with a flag.
- Core and Modern exclude a row when a predicate-required field is null or unknown and report the excluded volume by reason.
- Produce explicit membership flags and deterministic exclusion reason codes without overwriting source fields.
- Verify `Modern` is nested in `Core` and `Core` is nested in `Total`.
- Reconcile configured death-count, claim-amount, policy-exposure, and amount-exposure controls at release precision.

## Public interface

Use the population-registry and dataset interfaces supplied by the starter repository. Do not embed production totals as row-level logic.

## Evaluator checks

The evaluator will check every predicate boundary, null/unknown truth table, face-band normalization boundary, nesting, exclusion accounting, preservation of raw values, and control reconciliation.
