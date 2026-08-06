# C4 public smoke-test contract

Use the supplied `GroupingRequest` and metric registry. Read synthetic rows only through the starter repository's agreed input boundary; do not perform file I/O in `actual_to_expected.py`.

For each requested group and for the total population, return four ratio-of-sums results: count/amount and without/with mortality improvement. Preserve decimal-compatible additive totals. A zero expected total returns a null ratio and the stable reason code `zero_expected_denominator`.

Each result must retain the requested grouping dimensions, population identifier, period, actual field, expected field, MI flag, unit, and a deterministic evidence ID. The public smoke fixture deliberately includes a nonzero group and a zero-denominator group.
