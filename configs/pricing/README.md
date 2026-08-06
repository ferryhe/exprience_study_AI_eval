# Live pricing snapshots

Only official, dated pricing snapshots used by paid probes or benchmark runs belong here.

For each snapshot:

1. Conform to `benchmark_contracts/pricing_snapshot.schema.json`.
2. Identify the exact provider, effective model ID, service tier, official HTTPS source URL, effective timestamp, and decimal-string rates per million tokens.
3. Add the snapshot path, byte length, and SHA-256 to `pricing_manifest.json`.
4. Rerun both offline validators and the unit tests.

The live loader rejects unregistered files and every path outside `configs/pricing/`. Synthetic rates remain under `fixtures/pricing/` and cannot be used by live commands.
