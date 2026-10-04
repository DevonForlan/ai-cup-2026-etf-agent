"""MOPS (公開資訊觀測站) fetcher — STUB.

Planned: monthly revenue first-seen polling (t187ap05 / t21sc03), material information (重訊).
Not implemented in MVP-0: revenue history currently comes from FinMind with a conservative
availability assumption (day 10 of following month, config/data_sources.yaml)."""
from __future__ import annotations


def fetch_monthly_revenue_snapshot(*args, **kwargs):
    raise NotImplementedError("MOPS fetcher not implemented in MVP-0 (see DEVELOPMENT_STATUS.md)")


def fetch_material_info(*args, **kwargs):
    raise NotImplementedError("MOPS material-info fetcher not implemented in MVP-0")
