# Benchmark smoke fixtures

These files are synthetic, hand-verifiable benchmark inputs. They contain no SOA challenge records, policyholder information, protected raw data, hidden tests, gold outputs, or reference implementations.

- `codegen/c4/` is the small public A/E input used to smoke-test prompt assembly and a generated C4 submission. Its expected totals are evaluator-only and are not listed in its model-visible input manifest.
- `report/small_evidence/` is the small evidence bundle used to smoke-test evidence-only report generation. It is intentionally insufficient for an accepted actuarial report; a compliant model must identify those limitations.
- `pricing/synthetic_pricing_snapshot.json` contains invented unit-test rates only. It verifies Decimal cost arithmetic and must never be used for a paid run.

The benchmark loader verifies every model-visible artifact's path, type, byte count, and SHA-256 before a request can be sent.
