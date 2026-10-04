"""RuleBook = official rules + universe + official active ETF list + unconfirmed-rule assumptions."""
from __future__ import annotations

from dataclasses import dataclass

from agent.config import (Assumptions, OfficialRules, load_active_etfs, load_assumptions,
                          load_official_rules, load_universe)

SRC_RULES = "比賽辦法 §六"


@dataclass(frozen=True)
class RuleBook:
    rules: OfficialRules
    universe: dict[str, dict]          # ticker -> {name, market}
    active_etfs: list[str]             # official list (2026/9/11)
    assumptions: Assumptions

    @property
    def universe_set(self) -> set[str]:
        return set(self.universe)

    def authority_of(self, ticker: str) -> str:
        return "tpex" if self.universe.get(ticker, {}).get("market") == "TPEx" else "twse"


def load_rulebook(competition: str = "config/competition.yaml",
                  unconfirmed: str = "config/unconfirmed_rules.yaml") -> RuleBook:
    rules = load_official_rules(competition)
    ref = rules.raw.get("reference_files", {})
    uni = load_universe(ref.get("universe_csv", "config/universe_150.csv"))
    etfs = [e["etf"] for e in load_active_etfs(ref.get("active_etf_csv", "config/active_etf_list.csv"))]
    if len(uni) != 150:
        raise ValueError(f"universe must have 150 tickers, got {len(uni)}")
    return RuleBook(rules, uni, etfs, load_assumptions(unconfirmed))
