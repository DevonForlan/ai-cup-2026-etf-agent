# Architecture index

generated 2026-10-05T12:16:52.146451+08:00, git:7c1d6a1

## Documents

- [research/07_AGENT_ARCHITECTURE_RECOMMENDATION.md](../../research/07_AGENT_ARCHITECTURE_RECOMMENDATION.md)
- [agent/README.md](../../agent/README.md)
- [DEVELOPMENT_STATUS.md](../../DEVELOPMENT_STATUS.md)
- [docs/COMPETITION_DAILY_RUNBOOK.md](../../docs/COMPETITION_DAILY_RUNBOOK.md)
- [docs/EMERGENCY_RUNBOOK.md](../../docs/EMERGENCY_RUNBOOK.md)
- [docs/AGENT_AUTONOMY_EVIDENCE.md](../../docs/AGENT_AUTONOMY_EVIDENCE.md)
- [docs/STRATEGY_FREEZE_RECORD.md](../../docs/STRATEGY_FREEZE_RECORD.md)

## Modules (sha256 prefix)

| module | sha256 |
|---|---|
| agent/__init__.py | 01ba4719c80b6fe9 |
| agent/competition_day.py | 55fb697cdba2af2e |
| agent/config.py | 78ec9eea760473bc |
| agent/data/__init__.py | 01ba4719c80b6fe9 |
| agent/data/fetchers/__init__.py | e3b0c44298fc1c14 |
| agent/data/fetchers/corporate_actions.py | 1884ee5f5418a674 |
| agent/data/fetchers/etf_holdings.py | 5c49176528864f5a |
| agent/data/fetchers/finmind.py | a6918555cdf9a41f |
| agent/data/fetchers/material_info.py | 1e32636d9c0cffef |
| agent/data/fetchers/mops.py | 2488f69ba16c2215 |
| agent/data/fetchers/revenue_dates.py | b7f3da6e9af330e9 |
| agent/data/fetchers/taifex.py | 1beb8d4cfb6f0418 |
| agent/data/fetchers/tpex.py | ed5d410e42928c3e |
| agent/data/fetchers/twse.py | 77dfb5a2bbb8f3f1 |
| agent/data/http.py | a47965202f6814ac |
| agent/data/loaders.py | e417b5fade27a752 |
| agent/data/manifest.py | 8556d33906ba3b6c |
| agent/data/normalizers.py | c0fd684de95ebffe |
| agent/data/overnight.py | 22c9ecab627b7c87 |
| agent/data/pit.py | a217388bee6225c5 |
| agent/data/providers.py | a8a8138b1f88af33 |
| agent/dplan/__init__.py | 01ba4719c80b6fe9 |
| agent/dplan/builder.py | 58e69090a325dbd2 |
| agent/dplan/exporter.py | 278b7a4a9a5e30f1 |
| agent/dplan/funding.py | b616d4b78f6a4c48 |
| agent/dplan/graph.py | 194fb3832603b9b3 |
| agent/dplan/posture.py | e4b3f0f1d79b0471 |
| agent/engine/__init__.py | 01ba4719c80b6fe9 |
| agent/engine/active_share.py | 68d9e8aebdac9347 |
| agent/engine/compliance.py | 57fc5ce50124fff6 |
| agent/engine/fees.py | 9fa21aaf20e652dd |
| agent/engine/models.py | 61dab4506d17aadf |
| agent/engine/orders.py | c8ca99b9952c972b |
| agent/engine/rules.py | ba9fc31ef1bd42e9 |
| agent/engine/validate_dplan.py | 2bef09c5e0a58cc1 |
| agent/features/__init__.py | 01ba4719c80b6fe9 |
| agent/features/feature_engine.py | 4935e44184ab6484 |
| agent/features/institutional.py | 1ababf85f70e0f7a |
| agent/features/momentum.py | 1531cc85fd4ce5d9 |
| agent/features/regime.py | 3b610f6da82cc1d4 |
| agent/features/relative_strength.py | ffe3eb659aa7be9e |
| agent/features/revenue.py | fcd3cf03015f30c4 |
| agent/features/volatility.py | a5d010bf46f8ee74 |
| agent/features/volume.py | 283c26310843aa9a |
| agent/llm/__init__.py | 01ba4719c80b6fe9 |
| agent/llm/base.py | 3c2e4281ef87cda3 |
| agent/llm/client.py | 46b69330813b8848 |
| agent/llm/env.py | 83351906d510dffa |
| agent/llm/grounding.py | 4b06e21625223231 |
| agent/llm/interfaces.py | e7ead7c580f4cd31 |
| agent/llm/logging.py | 22acaac7ad946a9a |
| agent/llm/providers/__init__.py | e3b0c44298fc1c14 |
| agent/llm/providers/anthropic.py | 14a6dcdea765bc06 |
| agent/llm/providers/gemini.py | afa9abfa090ba6f5 |
| agent/llm/providers/http_providers.py | 372409b3e1e5a0d4 |
| agent/llm/providers/mock.py | 089bb9188c2626b7 |
| agent/llm/providers/openai.py | 3dc8a4bb317d93f6 |
| agent/llm/replay.py | 3a4e8783da87e57a |
| agent/llm/schemas.py | 40a979409d2ad678 |
| agent/ops/__init__.py | 31a9094f2d1cb026 |
| agent/ops/archive_run.py | 2b41563e8c26ba88 |
| agent/ops/audit.py | 618eb35599fc4c99 |
| agent/ops/common.py | 311ac31b2dd793e7 |
| agent/ops/deadline.py | 467e37af2cf7847b |
| agent/ops/healthcheck.py | e91c33266e401b32 |
| agent/ops/llm_review.py | c5e856f2795e23b9 |
| agent/ops/package_submission.py | e732f62219df4675 |
| agent/ops/preflight.py | fd10cb2306d5c3cd |
| agent/ops/reconcile.py | 315a64cc4131a98c |
| agent/ops/refresh_daily.py | ad8d3e2bd9f0902b |
| agent/ops/runbook.py | c9b2c4aac62d8f72 |
| agent/ops/settle_internal.py | a7c675cca8cd1e7b |
| agent/ops/settlement.py | f9bab48ca45fe2e2 |
| agent/pipeline.py | 8178efa1b9a7d71d |
| agent/portfolio/__init__.py | 01ba4719c80b6fe9 |
| agent/portfolio/baseline.py | 81620c20e1a0af94 |
| agent/portfolio/constructor.py | a4770e59664328bb |
| agent/portfolio/decisions.py | cf25c4107b2d34d4 |
| agent/portfolio/ranking.py | f70d9964202de62b |
| agent/portfolio/signal_fusion.py | dc4afc03f67c7db1 |
| agent/research/__init__.py | e3b0c44298fc1c14 |
| agent/research/active_share_report.py | 449a8b479494976d |
| agent/research/analyze.py | 29c9112ef110433d |
| agent/research/evaluate.py | 5a64b802a8629bb6 |
| agent/research/event_extractor.py | de607a108d9cfec7 |
| agent/research/event_study.py | c7a13299127e873b |
| agent/research/llm_eval.py | 01e65f1a9600b301 |
| agent/research/market_narrator.py | 2bea1f972c0c8853 |
| agent/research/reviewer.py | 86644ec0f22cd359 |
| agent/research/sensitivity.py | 3da2ff587495ec87 |
| agent/research/strategies.py | 8db4ae22b5eeafd6 |
| agent/research/strategies_r04.py | d11593baf114fa79 |
| agent/research/thesis_writer.py | 67036f3fe0edf26e |
| agent/risk/__init__.py | e3b0c44298fc1c14 |
| agent/risk/crash_guard.py | 8cd3e13e1ada19ee |
| agent/run_daily.py | 06f20b55071acaab |
| agent/run_sim.py | a69088cc06046e65 |
| agent/sim/__init__.py | 01ba4719c80b6fe9 |
| agent/sim/calendar.py | cdd9c8e0a4db541f |
| agent/sim/metrics.py | 3ad6f7d7b87502b8 |
| agent/sim/models.py | 1fd824358f6d1f24 |
| agent/sim/settle.py | ef80ff0ca2b0c599 |
| agent/tools/__init__.py | 01ba4719c80b6fe9 |
| agent/tools/backfill.py | 05f18d780fc7909b |
| agent/tools/benchmark.py | 7db4e349ab5ea4a5 |
| agent/tools/llm_runtime_benchmark.py | b35c40afc4cb8552 |
| agent/tools/make_fixture.py | 03db7f52d3ba105f |
