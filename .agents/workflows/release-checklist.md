---
description: Release check list
---

1) Security:
   - URL fetching restricted (optional allowlist)
   - max upload size
   - safe file path handling (no traversal)
2) Performance:
   - worker count documented and configurable
3) HA cluster:
   - cluster_config.json validated on startup
   - proxy recursion protection using internal=1
4) Observability:
   - logs + basic metrics
5) Dashboard:
   - partial cluster reachability handled gracefully
6) Parity:
   - tests passing
