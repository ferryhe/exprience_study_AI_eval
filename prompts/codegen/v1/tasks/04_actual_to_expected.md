# C4 — Actual-to-expected calculations

## Objective

Implement authoritative grouped count and amount actual-to-expected calculations, with and without mortality improvement.

## Allowed paths

- `src/soa_experience/calculations/actual_to_expected.py`
- `src/soa_experience/calculations/uncertainty.py`

## Required behavior

For every requested group, calculate ratio-of-sums:

- count A/E: `sum(Death_Count) / sum(ExpDth_VBT2015_Cnt)`;
- amount A/E: `sum(Death_Claim_Amount) / sum(ExpDth_VBT2015_Amt)`;
- count A/E with MI: `sum(Death_Count) / sum(ExpDth_VBT2015wMI_Cnt)`; and
- amount A/E with MI: `sum(Death_Claim_Amount) / sum(ExpDth_VBT2015wMI_Amt)`.

Never average cell-level A/E ratios. A zero expected denominator returns null plus a stable reason code. Preserve authoritative additive measures in exact decimal-compatible form and apply rounding only at the declared publication boundary.

Every result carries population, actual measure, expected field, MI basis, unit, period, grouping dimensions, rounding rule, credibility flag, and deterministic evidence ID. Implement approved 95% count Poisson intervals and the starter repository's reconciled amount-moment interface; do not invent an amount-uncertainty formula if that contract is absent.

## Public interface

Use the supplied metric registry and grouping request models. Do not read raw files directly from this module.

## Evaluator checks

The evaluator will check ratio-of-sums, all four bases, grouping, zero denominators, decimals, metadata, deterministic IDs, Poisson edge cases, and appropriate incomplete handling for an absent amount-moment contract.
