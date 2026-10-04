"""Settlement state carried from day to day (mirrors the organiser's daily settlement)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

from agent.config import D


@dataclass
class DayMarket:
    """T-day market data for settlement: per ticker VWAP inputs and close."""
    date: str
    close: dict[str, Decimal]
    amount: dict[str, Decimal] = field(default_factory=dict)   # 成交金額
    volume: dict[str, Decimal] = field(default_factory=dict)   # 成交股數
    cash_dividend: dict[str, Decimal] = field(default_factory=dict)       # ex-date today, TWD/share
    stock_dividend_per_share: dict[str, Decimal] = field(default_factory=dict)

    def vwap(self, t: str) -> Decimal | None:
        a, v = self.amount.get(t), self.volume.get(t)
        if a is None or v is None or D(v) == 0:
            return None
        return D(a) / D(v)


@dataclass
class Settlement:
    date: str                                  # settlement date (YYYY-MM-DD); "initial" day uses start-1
    holdings: dict[str, int]
    cash: Decimal
    nav: Decimal
    accrued_dividends: Decimal = Decimal(0)
    fees: Decimal = Decimal(0)                 # today's fees
    tax: Decimal = Decimal(0)                  # today's tax
    cum_fees: Decimal = Decimal(0)
    cum_tax: Decimal = Decimal(0)
    orders: list[dict] = field(default_factory=list)
    executions: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)   # today's warning events
    warning_count: int = 0
    dq: bool = False
    dq_reasons: list[str] = field(default_factory=list)
    nav_history: list[list] = field(default_factory=list)  # [[date, nav], ...] (excl. accrued)
    mdd: dict = field(default_factory=dict)
    turnover: Decimal = Decimal(0)             # today's traded value / prev NAV
    cum_turnover: Decimal = Decimal(0)
    drift_tracker: dict[str, int] = field(default_factory=dict)   # ticker -> consecutive days over cap
    active_share_breach_days: int = 0
    trades_void: bool = False
    submitted: bool = True
    closes: dict[str, Decimal] = field(default_factory=dict)       # closes used for NAV
    assumptions: dict = field(default_factory=dict)
    initial_nav: Decimal | None = None             # competition starting NAV (for MDD incl. initial)
    agent_state: dict = field(default_factory=dict)  # OUR strategy state (score EMA, entry dates); not official

    @property
    def nav_with_accrued(self) -> Decimal:
        return self.nav + self.accrued_dividends

    def to_dict(self) -> dict:
        def conv(x):
            if isinstance(x, Decimal):
                return str(x)
            if isinstance(x, dict):
                return {k: conv(v) for k, v in x.items()}
            if isinstance(x, list):
                return [conv(v) for v in x]
            return x
        d = conv(asdict(self))
        d["nav_with_accrued"] = str(self.nav_with_accrued)
        return d

    def save(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def from_dict(cls, d: dict) -> "Settlement":
        dec = {"initial_nav", "cash", "nav", "accrued_dividends", "fees", "tax", "cum_fees", "cum_tax", "turnover", "cum_turnover"}
        kw = {}
        for k, v in d.items():
            if k == "nav_with_accrued":
                continue
            if k in dec:
                kw[k] = D(v) if v is not None else None
            elif k == "holdings":
                kw[k] = {t: int(s) for t, s in v.items()}
            elif k == "closes":
                kw[k] = {t: D(p) for t, p in v.items()}
            else:
                kw[k] = v
        return cls(**kw)

    @classmethod
    def load(cls, path: Path | str) -> "Settlement":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def initial(cls, date: str, cash) -> "Settlement":
        c = D(cash)
        return cls(date=date, holdings={}, cash=c, nav=c, nav_history=[], initial_nav=c)
