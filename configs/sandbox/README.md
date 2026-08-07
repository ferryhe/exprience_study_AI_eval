# Code-generation sandbox policies

Policies in this directory are public, versioned execution contracts. A policy
in `pre_freeze` state permits materialization and static scanning only. It must
not execute generated code or support confirmatory scoring.

Freezing a policy requires a digest-pinned container image and verified Docker
or WSL2 isolation evidence. Native host execution is never an automatic
fallback.
