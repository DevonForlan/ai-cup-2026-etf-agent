# Audit evidence

Generated 2026-10-05T12:46:21.092735+08:00 at git:7e7a3b0 by `agent/ops/audit.py`. Regenerate any time; it never copies raw data.

| folder | content |
|---|---|
| architecture/INDEX.md | architecture docs + every agent module with sha256 |
| prompts/PROMPTS.json | prompt files, versions, sha256 |
| configs/CONFIGS.json | every config/*.yaml sha256 + strategy freeze record |
| runs/RUNS.json | 6 archived runs: archive/YYYYMMDD/<run_id>/ARCHIVE_MANIFEST.json sha256 |

Verification: re-hash a file and compare with the manifest; every archived D-Plan sha256 is in RUNS.json and in the run's package/manifest.json. Raw market data is referenced by the store manifest hash in each run's data_health.json / run_metadata.json (data_snapshot_hash), not copied.
