---
name: cluster-ha-routing
description: Implements the internal HA cluster pattern (round-robin submit + deterministic proxy routing) for the video classifier service.
---

# Cluster HA Routing Skill

## Requirements
- Shared-nothing nodes
- Round-robin job creation across healthy nodes
- Job ID prefix determines owner node
- Proxy with internal=1 to avoid recursion
- Cluster dashboard aggregates via fan-out to /admin/jobs

## Implementation checklist
- cluster_config loader (self_name + nodes + intervals)
- deterministic routing:
  - parse job_id -> owner node
- proxy rules:
  - forward method/headers/body
  - append internal=1
  - timeouts map to 503

## Included resources
- resources/cluster_config.example.json
- resources/routing_rules.md
