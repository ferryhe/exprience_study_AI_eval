# C5 — Segmented exhibits and evidence IDs

## Objective

Build deterministic exhibit tables from validated population data and registered metrics.

## Allowed paths

- `src/soa_experience/exhibits/definitions.py`
- `src/soa_experience/exhibits/build.py`
- `src/soa_experience/evidence/identifiers.py`

## Required behavior

- Support registered Total/Core/Modern, observation year, product, plan, face band, sex, smoker, age basis, issue age, attained age, duration, Select/Ultimate, and preferred-class dimensions.
- Calculate only registered count/amount and with/without-MI metrics through the authoritative calculation interface.
- Produce stable sort order, explicit dimension domains, null/unknown categories, units, population, period, basis, rounding, and evidence IDs.
- Flag or suppress sparse cells according to supplied credibility policy without changing reconciled totals.
- Store one logical exhibit as deterministic Parquet-ready rows plus compact JSON-ready metadata; do not render charts in this task.
- Ensure every displayed aggregate can resolve to one evidence record and that cross-filtered detail totals reconcile to the parent exhibit.

## Public interface

Implement the registered exhibit definitions and builder interfaces. Do not create unregistered exploratory segment combinations.

## Evaluator checks

The evaluator will check segmentation completeness, stable order/IDs, aggregate reconciliation, sparse-cell behavior, null categories, metadata propagation, and byte-identical output on shuffled input.
