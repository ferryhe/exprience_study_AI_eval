# Shared code-generation instructions

Implement only the bounded task in the accompanying task record. Use the supplied starter-repository interfaces and pinned dependencies. Target Python 3.12 and follow the repository's existing style.

Authoritative aggregation uses Polars lazy operations and explicit schemas. Preserve raw categorical values; put normalized values in separate fields. Use exact decimal-compatible representations for additive measures and released ratios. Float64 is permitted only where the task explicitly concerns modeling and must reconcile to deterministic results.

Do not add network calls, model-provider calls, dynamic package installation, unpinned dependencies, notebooks, generated binaries, secrets, hidden-test probes, or changes outside the allowed paths. Do not modify public tests or weaken validation to make examples pass.

Return one JSON object conforming to the code-submission schema. `files` contains complete UTF-8 text for allowed paths, not diffs or archives. Use NFC-normalized POSIX relative paths. Do not use absolute paths, backslashes, dot segments, symlinks, duplicate paths, or case-insensitive path collisions. Keep each file under 250,000 UTF-8 bytes and the response's combined file content under 1,000,000 bytes.

Do not claim code or tests were executed. Record assumptions, known limitations, and the tests the evaluator should run. If required interfaces or fixtures are missing, return `incomplete` or `blocked` with the reason instead of inventing them.
