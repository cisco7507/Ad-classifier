# Job States

queued -> processing -> completed
queued -> processing -> failed

Fields:
- id (prefixed with node name)
- mode: pipeline|agent
- input: urls[]|folder|upload
- settings_json
- status
- progress (0..1)
- result_json (final record: brand/category/confidence/reasoning/etc)
- artifacts_json (frames list, ocr_text path, plots)
- logs_jsonl (agent steps)
- created_at, updated_at, attempts, error
