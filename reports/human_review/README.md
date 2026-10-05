# Human review — real LLM narrative

REAL_LLM_STATUS = **BLOCKED_NO_API_KEY**

No real-provider run was possible, so there is nothing to review yet. After an API key is configured (docs/REAL_LLM_SETUP.md) run:

    .venv\Scripts\python.exe agent\ops\llm_review.py --llm-config config\llm_narrative_v1.yaml --provider google --days 15

One `YYYY-MM-DD_review.md` per day will appear here (template vs LLM side by side, facts, sources, deterministic reviewer A–I). Pipeline-only mock output: reports/round05_mock_pipeline_check/.
