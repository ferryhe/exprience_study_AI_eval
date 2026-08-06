# C1 — Source registration, ingestion, and schema

## Objective

Implement deterministic registration of the supplied ILEC TSV and dictionary plus explicit-schema ingestion to partitioned Parquet.

## Allowed paths

- `src/soa_experience/sources/manifest.py`
- `src/soa_experience/data/schema.py`
- `src/soa_experience/data/ingest.py`

## Required behavior

- Register path or URL, byte length, SHA-256, retrieval timestamp supplied by configuration, media type, terms note, and approval status without mutating raw inputs.
- Require the frozen 30-column header and explicit source data types; do not infer the production schema from a sample.
- Stream or lazily scan the 12.48 GB TSV without loading the complete source into memory.
- Write deterministic Parquet partitioned by `Observation_Year` with explicit ordering and stable configuration.
- Reconcile source and Parquet row counts plus configured additive control totals.
- Return a machine-readable dataset manifest and structured parse-reject information.
- Treat unexpected columns, missing columns, invalid observation years, hash mismatch, and any unapproved parse reject as blocking errors.

## Public interface

Implement the starter repository's declared `register_sources(config)` and ingestion interfaces without changing their signatures. Use only registered synthetic fixtures during development.

## Evaluator checks

The evaluator will check valid ingestion, header/type failures, source immutability, hash mismatch, reject handling, partitioning, row/control reconciliation, deterministic manifests, and bounded-memory behavior.
