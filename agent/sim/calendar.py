"""Trading calendar. Replay mode: dates present in the price history. Live mode: weekdays
minus configured holidays. The competition's first trade date is UNCONFIRMED (NC-15)."""
from __future__ import annotations

from datetime import date, timedelta


class TradingCalendar:
    def __init__(self, days: list[str]):
        self.days = sorted(set(days))
        self._idx = {d: i for i, d in enumerate(self.days)}

    @classmethod
    def weekdays(cls, start: str, end: str, holidays: list[str] | None = None) -> "TradingCalendar":
        hs = set(holidays or [])
        d, e = date.fromisoformat(start), date.fromisoformat(end)
        out = []
        while d <= e:
            if d.weekday() < 5 and d.isoformat() not in hs:
                out.append(d.isoformat())
            d += timedelta(days=1)
        return cls(out)

    def is_trading_day(self, d: str) -> bool:
        return d in self._idx

    def prev(self, d: str) -> str | None:
        if d in self._idx:
            i = self._idx[d]
            return self.days[i - 1] if i > 0 else None
        earlier = [x for x in self.days if x < d]
        return earlier[-1] if earlier else None

    def next(self, d: str) -> str | None:
        later = [x for x in self.days if x > d]
        return later[0] if later else None

    def between(self, start: str, end: str) -> list[str]:
        return [d for d in self.days if start <= d <= end]
