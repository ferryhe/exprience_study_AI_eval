# Code-generation sandbox policies

Policies in this directory are public, versioned execution contracts. A policy
in `pre_freeze` state permits materialization and static scanning only. A
`frozen` policy may execute only through its declared digest-pinned Docker
image; native host execution is never a fallback.

Rebuild and verify the C4 image with:

```text
python scripts/build_codegen_sandbox.py
```
