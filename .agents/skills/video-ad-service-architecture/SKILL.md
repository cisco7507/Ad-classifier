---
name: video-ad-service-architecture
description: Defines the API + worker + storage + dashboard architecture for the Video Ad Classifier (ported from combined.py) using the LangID cluster model.
---

# Video Ad Service Architecture Skill

## When to use
Use this skill when designing endpoints, DB schema, storage layout, or dashboard data flows.

## Hard constraints
- Must implement internal HA cluster patterns (round-robin submit + proxy-to-owner + aggregated dashboard endpoints).
- Must expose all Gradio functionality as API calls.
- Must not implement audio language gate features.

## Deliverables
1) API contract (paths + schemas)
2) Job lifecycle + states
3) Storage layout for video jobs (frames, OCR output, artifacts)
4) Dashboard contract (endpoints it consumes)

## Reference artifacts
- resources/api_contract.md
- resources/job_states.md
