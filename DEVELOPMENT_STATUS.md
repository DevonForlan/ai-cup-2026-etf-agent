# DEVELOPMENT STATUS

> Last update: 2026-10-05 (Round 04). Round 04 report: `reports/ROUND_04_LLM_INTEGRATION_REPORT.md`.
> (Round 03 notes below still apply.) Reports: `reports/ROUND_03_STRATEGY_OPTIMIZATION_REPORT.md` (strategy),
> `logs/development/ROUND_02_DEVELOPMENT_REPORT.md` (MVP-0). AI-generated — human review required (company policy).

## Version control
Git repo since Round 03 (`git log`). `code_version = git:<short_sha>`; uncommitted changes in `agent/` or
`config/` → `git:<sha>-dirty` + warning; `run_daily.py --competition` refuses to run on a dirty tree.

## Phases
| Phase | Status | Notes |
|---|---|---|
| P1 Competition Engine / Validator | ✅ | unchanged from R02 (+ odd-lot handling in constructor) |
| P2 NAV Simulator | ✅ | + agent_state, research-only cost/slippage stress |
| P3 PIT Data | ✅ (most) | 2024-03→2026-10 prices/insti; real active-ETF holdings 30/30; corporate actions; revenue (legal-deadline availability + MOPS first-seen observer); TAIFEX night; SPX/NDX/SOX/TSM/USDTWD. Atomic writes + locked manifests |
| P4 Features | ✅ v2 | + overnight features, EW-universe trend/vol |
| P7 Portfolio | ✅ v2 | turnover controls (EMA, rank buffer, min hold, swap margin, threshold, penalty, rebalance frequency/hold mode), daily change cap, stress-retry, odd-lot lock |
| P8 Risk/Compliance | ✅ | + regime v0 (soft cash only, opt-in) |
| P9 D-Plan | ✅ | overnight facts cite TAIFEX / US / CBC sources |
| P11 Walk-forward | ✅ | 5 windows × 24 days, 54 strategies + 36 sensitivity variants + stress; random 1000× MC |
| P5 LLM | ✅ built, ⏸ not enabled | provider-agnostic client (REST adapters untested: no API key), mock/replay/template, grounded event extractor, narrator/thesis/reviewer, bounded fusion; evaluated with MOCK only |
| Crash Guard | ✅ built, ⏸ not enabled | deterministic state machine; W2 MDD only −0.4~0.9pp, W5 −1.6pp; passive cash-drift fix kept |
| P10 Memory | ⏸ | strategy state only |

## Tests
`.venv\Scripts\python.exe -m pytest` → **225 passed, 0 failed** (~70 s).

## Quant Core v1
`config/strategy_quant_v1.yaml` (frozen; selected = HN_rev: revenue_yoy 0.7 + revenue_mom 0.3, buy day 1 then hold,
compliance-only adjustments). Cross-window: median +1.71%, median excess vs random p50 +0.40% (3/5 windows),
cost 0.13%, 0 violations / 0 fallbacks. Edge is NOT statistically significant; selection is driven by cost,
compliance and robustness. Worst risk: 28.6% intra-window MDD in the April-2025 crash window.

## Runtime
Single run_day (uncontended, 16-core laptop): data load 0.8 s, cold 1.08 s, warm 0.34 s, peak RSS 261 MB.

## Known Issues
1. Hold-style v1 does not de-risk in crashes (W2 MDD 20–29% for all hold strategies).
2. 5 ETFs (統一 00981A/00403A, 安聯 00984A/00993A, 台新 00987A) only expose the latest day → need daily scheduled fetch.
3. Issuer ETF endpoints are undocumented and may change; issuer site terms not individually reviewed.
4. SOX / TSM ADR come from Yahoo's unofficial chart API; FRED may not be updated by 05:30 for live runs.
5. Revenue per-company publish times unavailable historically (legal deadline used → slower but leak-free).
6. All windows use the 2026/7 universe → survivorship/hindsight bias (not corrected this round).
7. No submission module; live mode not yet exercised in a real 19:30–08:55 window.
8. `data/raw` is large (TPEx all-securities responses; ETF/CA raw files).

## Unconfirmed rules
See `config/unconfirmed_rules.yaml` and report §17 (NC-1, NC-2, NC-3, NC-4, NC-5, NC-6, NC-7, NC-8, NC-9, NC-10, NC-15, C12 fees).

## Round 04 decisions
- Competition config stays `config/strategy_quant_v1.yaml` (Quant-only, template narrative).
- `config/llm_narrative_v1.yaml` prepared (text only) — enable only after a real-provider replay review.
- No `strategy_quant_llm_v1.yaml`: event signal showed no measurable benefit / no directional value (mock).
- Cash ceilings must leave room for passive drift (settled cash ratio > 25% is a warning regardless of cause).
- `logs/llm/` is gitignored: archive it daily during the competition (replay + 12/2 review evidence).

## Next steps
1. Phase 5 LLM behind existing interfaces (text writers first; event extraction as bounded overlay, ablated vs v1).
2. Event-driven rebalance after monthly-revenue deadline (H10_rev-like) as a v1.1 candidate — test, don't assume.
3. Crash protection research (regime-driven cash, not LLM timing).
4. Scheduled daily jobs: ETF holdings, MOPS revenue first-seen, overnight data; live dry run; submission mechanism.
