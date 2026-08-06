# SOA Life Insurance Experience Study — Final Delivery Specification

**Status:** Final

**Delivery window:** 2026-08-06 to 2026-09-04

**Scope:** Objective 2 subproject — deterministic data-to-report and interactive experience-study application

## 1. Product definition

Given the supplied SOA ILEC 2012-2019 dataset, the product will perform the complete controlled workflow from data registration through actuarial calculation and publication. It has one authoritative calculation backend and two publication surfaces:

1. An English SOA-style research report in canonical JSON, HTML, and PDF.
2. A Tableau-like interactive web application for filtering, drilling into, tabulating, charting, and exporting the same validated results.

The four AI models receive the same frozen evidence bundle, prompt bytes, output schema, and run budget. They produce four comparable raw report outputs. AI-generated text never becomes the source of a calculation.

```text
SOA TSV + dictionary + mortality tables
              |
              v
 deterministic validation and actuarial engine
              |
              v
 canonical Parquet + exhibit tables + evidence bundle
              |
      +-------+------------------+
      |                          |
      v                          v
 SOA-style report        interactive web application
      |
      v
 four-model report comparison and scorecard
```

## 2. Authoritative inputs and reference targets

### 2.1 Local input

| Item | Location/fact |
|---|---|
| Experience data | `data/ILEC_2012_19 - 20240429.txt` |
| Data dictionary | `data/ILEC 2012_19 - Data Dictionary.xlsx` |
| TSV size | 12,477,136,749 bytes |
| Data rows | 45,501,036, excluding the header |
| Columns | 30 |
| Observation years | 2012-2019 |
| Required source combinations | all 24 combinations of `ALB/ANB x F/M x NS/S/U x Select/Ultimate` |

These facts are release invariants. A mismatch blocks the run unless a new source version is explicitly registered.

### 2.2 Public references

- Local reference inventory and hashes: `data/reference/soa/source_inventory.json`
- SOA challenge: https://www.soa.org/research/opportunities/2025/ai-life-ins-challenge/
- Reference study: https://www.soa.org/resources/research-reports/2024/ilec-mort-2012-19/
- Target main report: https://www.soa.org/globalassets/assets/files/resources/research-report/2024/ilec-mort-main.pdf
- 2015 VBT methodology and mortality-improvement references: https://www.soa.org/resources/experience-studies/2015/2015-valuation-basic-tables/
- Reference appendices: https://www.soa.org/globalassets/assets/files/resources/research-report/2024/ilec-mort-appendices.xlsx
- Target Tableau experience: https://tableau.soa.org/t/soa-public/views/ILEC2012-2019ExperienceData-Final/Notes

The target is functional and analytical equivalence, not visual or textual copying. The new report and web application must expose comparable study definitions, trends, segments, limitations, and drill-down capability while retaining independent presentation and implementation.

### 2.3 Expected-death basis

The following supplied fields are authoritative inputs:

- `ExpDth_VBT2015_Cnt`
- `ExpDth_VBT2015_Amt`
- `ExpDth_VBT2015wMI_Cnt`
- `ExpDth_VBT2015wMI_Amt`
- `Cen2MomP1wMI_Amt`
- `Cen2MomP2wMI_Amt`
- `Cen3MomP1wMI_Amt`
- `Cen3MomP2wMI_Amt`
- `Cen3MomP3wMI_Amt`

The application aggregates these fields directly. It does not replace them with newly generated expected values.

Twelve public SOA MORT XML tables provide an independent `q` validation:

| Age basis | Sex | Class | Table ID |
|---|---|---|---:|
| ALB | F | NS RR100 | 3214 |
| ANB | F | NS RR100 | 3224 |
| ALB | F | S RR100 | 3230 |
| ANB | F | S RR100 | 3234 |
| ALB | M | NS RR100 | 3242 |
| ANB | M | NS RR100 | 3252 |
| ALB | M | S RR100 | 3258 |
| ANB | M | S RR100 | 3262 |
| ANB | M | Unismoke | 3273 |
| ANB | F | Unismoke | 3274 |
| ALB | M | Unismoke | 3275 |
| ALB | F | Unismoke | 3276 |

Each XML source is `https://mort.soa.org/data/t{table_id}.xml`. Select lookup uses issue age and duration; Ultimate lookup uses attained age. Juvenile issue ages use the corresponding Unismoke table. XML reconstruction must have zero missing lookup keys and meet the frozen precision tolerances. The TSV expected fields remain authoritative because the published XML rates have less precision.

## 3. Final deliverables

| ID | Deliverable | Required content |
|---|---|---|
| D1 | Deterministic calculation package | validation, populations, A/E, uncertainty, segmentation, exhibits, model ladder, evidence bundle |
| D2 | Analytical data store | immutable source manifest, partitioned Parquet, aggregate exhibit tables, hashes, metric registry |
| D3 | Reference report | validated English report, practitioner summary, exhibits, limitations, provenance; JSON/HTML/PDF |
| D4 | Interactive web application | Tableau-like filters, KPIs, charts, tabular drill-downs, downloads, evidence/provenance views |
| D5 | Four raw model reports | one predesignated JSON/HTML/PDF output for each approved model using identical prompt/input |
| D6 | Provider scorecard | code quality, report quality, latency, tokens, API cost, failures, and human repair time |
| D7 | API and CLI | stable Python API, command-line interface, and versioned REST endpoints |
| D8 | Reproducibility package | configuration, manifests, prompts, schemas, tests, container/lockfile, replay command, review records |

Release layout:

```text
outputs/release/
|-- reference_report/{report.json,report.html,report.pdf,summary.pdf}
|-- dashboard/{dist/,dashboard_manifest.json}
|-- primary/
|   |-- gpt-5.6-sol/{report.json,report.html,report.pdf,run_manifest.json,validation.json}
|   |-- claude-opus-5/{report.json,report.html,report.pdf,run_manifest.json,validation.json}
|   |-- kimi-k3/{report.json,report.html,report.pdf,run_manifest.json,validation.json}
|   `-- deepseek-v4-pro/{report.json,report.html,report.pdf,run_manifest.json,validation.json}
|-- scorecard/{code_metrics.parquet,report_metrics.parquet,comparison.html}
|-- evidence_bundle/
`-- replay/
```

## 4. Deterministic analytical system

### 4.1 Source registration and validation

Every source is registered with URL/location, byte length, SHA-256, retrieval timestamp, media type, terms note, and approval status. Raw inputs are immutable.

Blocking validation includes:

- exact header, 30 columns, 45,501,036 rows, encoding, parse-reject count, and data types;
- all 24 age-basis/sex/smoker/select-ultimate combinations;
- observation year 2012-2019;
- finite, nonnegative exposures, actuals, expected values, and moment fields;
- registered categorical domains and explicit null/unknown treatment;
- issue-age, attained-age, duration, issue-year, and age-basis relationship checks;
- raw-to-Parquet row-count and aggregate equality;
- zero missing XML mortality-rate lookups and tolerance-based expected-value reconciliation;
- Total/Core/Modern population nesting and published-volume reconciliation;
- exact reconciliation of every released metric and exhibit to the independent oracle.

Warnings do not silently disappear. Unknown codes, sparse cells, dictionary/source coding differences, and methodology-era changes are included in the review packet and web Data Quality page.

### 4.2 Canonical storage

- Preserve the TSV as the immutable source.
- Convert with an explicit schema to Parquet partitioned by `Observation_Year`.
- Use Polars lazy operations for authoritative transformation and aggregation.
- Preserve raw categorical values; place normalized values in separate versioned columns.
- Use Decimal128 for authoritative additive measures and ratios; Float64 is restricted to modeling and must reconcile to the decimal results.
- Store every exhibit as Parquet plus compact JSON/CSV. Report charts and web charts read the saved exhibit table rather than rerunning separate calculations.
- Use stable ordering, explicit rounding, pinned dependency versions, sorted JSON keys, and canonical content hashes.

### 4.3 Study populations

Population predicates are versioned and unit-tested:

- `total_v1`: all valid registered source rows.
- `core_v1`: `Issue_Age >= 18 AND SOA_Post_Lvl_Ind != 'PLT'`.
- `modern_v1`: Core plus `Issue_Year >= 2000`, face amount band 05-11, and `Insurance_Plan != 'Other'`.

Null or unknown values never pass a predicate implicitly. Total retains valid unknown categorical values with a flag; Core and Modern exclude a row when a required predicate is null or unknown and disclose the excluded volume.

Published volume controls:

| Population | Death count | Death claims | Policy exposure | Amount exposure |
|---|---:|---:|---:|---:|
| Total | 4,552,009 | $290.0B | 464,513,072 | $105,573B |
| Core | 4,125,283 | $279.0B | 365,681,412 | $100,262B |
| Modern | 290,123 | $141.8B | 177,118,100 | $85,603B |

### 4.4 Authoritative calculations

For any group `g`:

```text
Count A/E          = sum(Death_Count)        / sum(ExpDth_VBT2015_Cnt)
Amount A/E         = sum(Death_Claim_Amount) / sum(ExpDth_VBT2015_Amt)
Count A/E with MI  = sum(Death_Count)        / sum(ExpDth_VBT2015wMI_Cnt)
Amount A/E with MI = sum(Death_Claim_Amount) / sum(ExpDth_VBT2015wMI_Amt)
```

Rules:

- Always use ratio-of-sums, never the mean of cell A/E ratios.
- A zero expected denominator returns null plus a reason code.
- Every output carries population, measure basis, MI basis, units, period, rounding, and evidence ID.
- Count uncertainty uses approved 95% Poisson intervals.
- Amount uncertainty uses the supplied second- and third-central-moment components after formula reconciliation.
- Sparse cells below the approved credibility threshold are flagged or suppressed from ranking.
- Exploratory significance flags use the preregistered multiplicity rule.

### 4.5 Required segmentation and exhibits

All results support count and amount bases, with and without MI where meaningful:

1. Total/Core/Modern reconciliation.
2. Observation-year exposure, expected, actual, and A/E trends.
3. Sex and smoker status.
4. Product and observation year.
5. Face amount band and product.
6. Issue age, attained age, and duration.
7. Select versus Ultimate.
8. Preferred-class indicator, number of classes, and class rank.
9. Juvenile and older-age experience.
10. Data-quality, credibility, sparse-cell, and methodology-era flags.
11. Model calibration and variable effects.
12. Cross-filtered detail table backing every chart.

### 4.6 Approved model ladder

Models explain patterns; they do not replace deterministic totals.

1. Grouped A/E baseline and observation-year trend.
2. Poisson GLM on death counts with `log(expected deaths)` as offset.
3. XGBoost Poisson sensitivity model with `base_margin = log(expected deaths)`.

Primary time split is train 2012-2017, validate 2018, test 2019. Because data collection methodology changed in 2018-2019, the release includes a methodology-era indicator, restricted-feature sensitivity, and rolling-origin diagnostics. Model findings must be confirmed by deterministic follow-up tables before entering the report.

## 5. Evidence bundle

The evidence bundle is the single interface between calculation and narrative/dashboard publication.

```text
evidence_bundle/
|-- bundle_manifest.json
|-- source_manifest.json
|-- run_manifest.json
|-- validation_summary.json
|-- exception_register.json
|-- reconciliation.json
|-- population_registry.json
|-- metric_registry.json
|-- citation_registry.json
|-- tables/*.parquet
|-- tables/*.json
|-- charts/*.svg
|-- models/*/{specification.json,diagnostics.json}
`-- limitations.json
```

Each evidence item has a stable ID, definition, value or table locator, unit, population, source/run hash, rounding rule, and allowed narrative use. The report and web application must display identical values for the same evidence ID.

## 6. SOA-style report

The target is a 3,000-6,000 word English main report plus a 1-2 page practitioner summary.

Required sections:

1. Executive findings.
2. Data sources, validation, and exclusions.
3. Study populations and expected basis.
4. Exposure and high-level mortality trends.
5. Product results.
6. Sex, smoker, risk-class, and preferred results.
7. Issue-age, attained-age, duration, juvenile, and older-age results.
8. Model methodology, diagnostics, and explanatory findings.
9. Practical implications.
10. Limitations, reliance, governance, and appropriate use.
11. Reproducibility, exhibit index, and references.

Report production contract:

- The model receives only the frozen evidence bundle, report outline, limitation checklist, style guide, and output JSON Schema.
- Every numeric or comparative claim contains one or more evidence IDs.
- Structured report JSON is validated before rendering.
- Jinja templates produce canonical HTML; pinned Chromium produces PDF.
- Released numeric claims must pass value, unit, population, period, basis, and rounding checks.
- Unsupported material claims, unresolved contradictions, missing required limitations, or failed replay block release.

## 7. Tableau-like web application

### 7.1 Technology

- Backend: Python 3.12, FastAPI, Polars, Pydantic.
- Analytical storage: partitioned Parquet plus precomputed exhibit tables.
- Frontend: React, TypeScript, Vite, and Apache ECharts.
- Delivery: static frontend bundle served with the API or deployed separately against the versioned REST API.

The browser never receives the 12.48 GB raw TSV. It requests compact validated aggregates by evidence ID.

### 7.2 Pages

1. **Overview:** Total/Core/Modern KPIs, annual A/E trends, exposure composition, principal findings.
2. **Data Quality:** source hashes, row/field checks, exclusions, warnings, XML reconciliation, methodology-era notes.
3. **Mortality Trends:** actual, expected, A/E, confidence intervals, year and duration trends.
4. **Products and Face Amount:** product, face-band, plan, year, and cross-segment views.
5. **Demographics:** sex, smoker, age basis, issue age, attained age, juvenile, and older-age views.
6. **Risk Classification:** preferred indicator, number of classes, class rank, Select/Ultimate.
7. **Model Diagnostics:** GLM/XGBoost calibration, holdout results, residuals, and deterministic supporting tables.
8. **Exhibit Explorer:** sortable/filterable table for every published exhibit with CSV export.
9. **Provider Comparison:** four model reports, validation scores, unsupported claims, latency, cost, and reviewer outcomes.
10. **Definitions and Provenance:** population/metric definitions, evidence IDs, source versions, limitations, and run manifest.

### 7.3 Global filters

- Population: Total, Core, Modern.
- Metric: exposure, actual, expected, count A/E, amount A/E.
- Expected basis: without MI or with MI.
- Observation year.
- Age basis.
- Sex and smoker status.
- Product and face amount band.
- Issue age, attained age, and duration.
- Select/Ultimate.
- Preferred-class fields.

Filters are synchronized across KPIs, charts, and tables. Active filters appear in exported files and shareable URLs.

### 7.4 Web acceptance criteria

- Every displayed value resolves to a registered evidence ID and matches the report/evidence table.
- Warm aggregate query p95 is below 2 seconds on the recorded local release machine.
- Initial application load is below 5 seconds on the release environment using precomputed summaries.
- Filters, reset, drill-down, sorting, pagination, CSV export, and shareable URL state pass automated end-to-end tests.
- Charts have accessible titles, units, legends, tooltips, tabular alternatives, and color-safe palettes.
- Desktop and tablet layouts are usable; unsupported/mobile-wide tables degrade to scrolling rather than truncation.
- No unresolved validation error or unsupported claim is hidden by the interface.

## 8. Four-model comparison

Approved direct-API routes:

- `gpt-5.6-sol`
- `claude-opus-5`
- `kimi-k3`
- `deepseek-v4-pro`

### 8.1 Fairness contract

- Same normalized system prompt and user prompt bytes.
- Same evidence bundle, file order, output JSON Schema, context, budget, retry policy, and wall-clock limit.
- `prompt_manifest.json` stores prompt bytes and SHA-256.
- Provider adapters change only the API envelope; they add no hints or examples.
- Use the closest supported high-reasoning setting and record the effective settings.
- Cache is cold/disabled for primary cost and latency comparisons.
- Execute providers in randomized compact blocks and blind provider identity during human review.
- Record exact model ID, response ID, SDK/adapter version, region, timestamps, retries, token categories, price snapshot, and cost.

The four headline outputs are confirmatory repetition 1, designated before execution. They are not selected as best-of-n. A failed output remains visible; repaired and human-edited versions are stored separately.

### 8.2 Repetitions

- Pilot: 3 runs per model; excluded from confirmatory estimates.
- Report benchmark: 10 independent confirmatory runs per model.
- Code tasks: 10 independent runs per model for schema validation, population filters, A/E, exhibits, and Poisson modeling.
- Integration task: 5 runs per model.

### 8.3 Scorecard

Report-quality panel:

| Dimension | Weight |
|---|---:|
| Numeric claim accuracy | 30 |
| Evidence citation precision/recall | 20 |
| Unsupported-claim control | 15 |
| Useful actuarial insight | 15 |
| Limitations and governance | 10 |
| Clarity and reviewer acceptance | 10 |

Code-quality panel:

| Dimension | Weight |
|---|---:|
| Hidden-test execution | 40 |
| Actuarial correctness | 30 |
| Reproducibility | 15 |
| Dependency/security behavior | 10 |
| Maintainability | 5 |

Cost, latency, retries, failures, token usage, and human repair time are shown separately and on cost-quality Pareto views. Raw metrics and intervals remain primary; weighted scores are navigational summaries rather than the sole ranking.

## 9. Interfaces

### 9.1 Python API

```python
register_sources(config) -> SourceManifest
validate_study(config) -> ValidationReport
build_dataset(config) -> DatasetManifest
run_study(config) -> EvidenceBundle
fit_models(config, evidence) -> ModelBundle
render_reference_report(evidence) -> ReportArtifacts
generate_model_report(provider, evidence, prompt) -> ModelReportArtifacts
run_benchmark(config) -> BenchmarkResults
query_exhibit(exhibit_id, filters) -> ExhibitResponse
```

### 9.2 CLI

```text
soa-exp sources register
soa-exp validate
soa-exp build-parquet
soa-exp run-study
soa-exp fit-models
soa-exp build-evidence
soa-exp render-reference-report
soa-exp generate-report --provider <provider>
soa-exp benchmark
soa-exp serve
soa-exp replay --run-id <run_id>
```

### 9.3 REST API

- `POST /v1/studies`
- `GET /v1/studies/{study_id}`
- `GET /v1/studies/{study_id}/validation`
- `GET /v1/studies/{study_id}/exhibits`
- `GET /v1/exhibits/{exhibit_id}?filters=...`
- `POST /v1/reports`
- `POST /v1/benchmarks`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/artifacts/{artifact_id}`
- `GET /health`

Long-running jobs are asynchronous and return a job ID. APIs accept immutable source/configuration references rather than multi-gigabyte uploads.

## 10. Repository structure

```text
.
|-- pyproject.toml
|-- uv.lock
|-- configs/{studies,providers}/
|-- schemas/
|-- prompts/{prompt_manifest.json,codegen/,report/}
|-- src/soa_experience/
|   |-- sources/
|   |-- data/
|   |-- validation/
|   |-- populations/
|   |-- calculations/
|   |-- exhibits/
|   |-- models/
|   |-- evidence/
|   |-- reporting/
|   |-- providers/
|   |-- benchmark/
|   |-- web_api/
|   `-- cli.py
|-- web/
|-- gold/{definitions,appendix_cells,insight_inventory}/
|-- tests/{unit,integration,actuarial,regression,benchmark,e2e}/
|-- report/{templates,styles}/
|-- docs/
|-- outputs/
`-- data/ and runs/                 # gitignored
```

## 11. Release controls

- Independent aggregation oracle must reproduce every released metric and exhibit.
- Report and web values must match the same evidence IDs.
- All released numeric claims pass automatic validation.
- Zero unsupported material claims or unresolved contradictions.
- Required limitations and governance disclosures have 100% coverage.
- Two independent reviewers complete blinded qualitative scoring; an actuarial reviewer signs the release.
- Clean-environment replay reproduces canonical Parquet aggregates, evidence JSON, report HTML, and web data assets.
- PDF rendering uses pinned Chromium/fonts; canonical JSON/HTML hashes are the primary cross-platform reproducibility proof.
- API keys use approved secret storage. Raw TSV rows are not sent to model providers or browsers.
- ASOP 23, 25, 41, and 56 applicability and disclosures are recorded.

## 12. One-month delivery gates

| Date | Gate | Required result |
|---|---|---|
| Aug 12 | G1 Data freeze | source/XML hashes, schema, 45,501,036 rows, 24 combinations, population truth tables, expected-basis mapping, gold controls |
| Aug 19 | G2 Calculation freeze | Parquet, validations, Total/Core/Modern, A/E, uncertainty, independent reconciliation, performance baseline |
| Aug 26 | G3 Product beta | exhibits, models, evidence bundle, reference report, API/CLI, complete web beta |
| Aug 30 | G4 Benchmark freeze | exact prompts/input/schema, model IDs, adapters, budgets, tests, pilot completion |
| Sep 3 | G5 Candidate | four primary reports, all confirmatory runs, scorecard, web/package QA, review records |
| Sep 4 | Release | independent replay and actuarial/numerical/security sign-off; JSON/HTML/PDF/web/reproducibility handoff |

Secondary sensitivity work is deferred before any validation, reconciliation, or release control is weakened.

## 13. Definition of done

The project is complete only when a clean machine can take the registered ILEC inputs and one approved configuration, then:

1. validate the source and reproduce the registered study populations;
2. build canonical Parquet and reconciled exhibit tables;
3. calculate deterministic count/amount A/E with and without MI;
4. generate the evidence bundle and approved model diagnostics;
5. generate the validated SOA-style reference report;
6. generate four directly comparable model reports from the identical frozen prompt/input;
7. serve the Tableau-like web application using the same evidence;
8. reproduce the scorecard, cost, latency, and repair metrics; and
9. pass independent actuarial, numerical, security, accessibility, and replay review.
