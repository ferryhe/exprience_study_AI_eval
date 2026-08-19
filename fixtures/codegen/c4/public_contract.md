# C4 public smoke-test contract

Receive synthetic rows through the supplied `ExperienceInput` in-memory boundary. The benchmark harness constructs this object from the registered fixture using its `population_id`, `period`, and a Polars `LazyFrame`; do not perform file I/O in `actual_to_expected.py`.

For each requested group and for the total population, return four ratio-of-sums results: count/amount and without/with mortality improvement. Preserve decimal-compatible additive totals. A zero expected total returns a null ratio and the stable reason code `zero_expected_denominator`.

No reconciled amount-moment interface is supplied in this smoke fixture. Implement approved 95% count Poisson intervals and expose an explicit unavailable result for amount uncertainty instead of inventing a formula. This localized absence does not block grouped count or amount A/E calculations.

Each result must retain the requested grouping dimensions, population identifier, period, actual field, expected field, MI flag, unit, and a deterministic evidence ID. The public smoke fixture deliberately includes a nonzero group and a zero-denominator group.
