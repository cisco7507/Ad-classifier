---
description: implement HA cluster behaviors (round-robin submit + proxy-to-owner)
---

Goal: implement HA cluster behaviors (round-robin submit + proxy-to-owner).

Steps:
1) Implement cluster_config loader:
   - self_name, nodes map, health check interval, internal timeouts
2) Add background health checker updating in-memory node status.
3) Implement round-robin target selection for job creation:
   - skip unhealthy nodes
   - retry next healthy node if the chosen node is down
4) Implement proxy routing for job-specific endpoints:
   - parse job_id prefix => owner node
   - if owner != self => forward request with ?internal=1
   - prevent proxy loops when internal=1
5) Add cluster aggregation endpoints:
   - GET /admin/jobs (local only)
   - GET /cluster/jobs (fan-out aggregate)
   - GET /cluster/nodes (fan-out health)

Exit criteria:
- Can submit jobs to any node and still fetch results from any node
