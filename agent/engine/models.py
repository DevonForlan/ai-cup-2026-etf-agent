"""Structured check results shared by compliance and D-Plan validation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    UNKNOWN = "UNKNOWN"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _jsonable(x: Any) -> Any:
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, Enum):
        return x.value
    return x


@dataclass
class CheckResult:
    rule_id: str
    status: Status
    message: str
    actual: Any = None
    limit: Any = None
    source: str = ""
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))


@dataclass
class Report:
    name: str
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, rule_id: str, status: Status, message: str, actual=None, limit=None,
            source: str = "", **detail) -> CheckResult:
        c = CheckResult(rule_id, status, message, actual, limit, source, detail)
        self.checks.append(c)
        return c

    def extend(self, other: "Report") -> None:
        self.checks.extend(other.checks)

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == Status.FAIL]

    @property
    def ok(self) -> bool:
        return not self.failures

    def by_rule(self, rule_id: str) -> list[CheckResult]:
        return [c for c in self.checks if c.rule_id == rule_id]

    def statuses(self, rule_id: str) -> set[Status]:
        return {c.status for c in self.by_rule(rule_id)}

    def summary(self) -> dict:
        out: dict[str, int] = {}
        for c in self.checks:
            out[c.status.value] = out.get(c.status.value, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "summary": self.summary(),
                "checks": [c.to_dict() for c in self.checks]}
