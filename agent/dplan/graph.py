"""Internal Evidence Graph (superset of the D-Plan).

Node kinds: RawSnapshot, Source, Fact, Signal, MarketView, Inference, TargetPortfolio,
Decision, Order, ValidationReport. Internal IDs are semantic keys (e.g. "fact:2330:2026-10-26");
D-Plan IDs (S1, O1, I1, D1) are assigned only at export time, over the nodes reachable from
market_view / decisions / no_trade_decisions / orders, in first-use order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    kind: str
    key: str
    data: dict[str, Any] = field(default_factory=dict)
    refs: list[str] = field(default_factory=list)      # keys of upstream nodes


class EvidenceGraph:
    def __init__(self, trade_date: str):
        self.trade_date = trade_date
        self.nodes: dict[str, Node] = {}
        self.order: list[str] = []

    def add(self, kind: str, key: str, data: dict | None = None, refs: list[str] | None = None) -> Node:
        if key in self.nodes:
            n = self.nodes[key]
            if data:
                n.data.update(data)
            for r in refs or []:
                if r not in n.refs:
                    n.refs.append(r)
            return n
        for r in refs or []:
            if r not in self.nodes:
                raise KeyError(f"{key} references unknown node {r}")
        n = Node(kind, key, dict(data or {}), list(refs or []))
        self.nodes[key] = n
        self.order.append(key)
        return n

    def of_kind(self, kind: str) -> list[Node]:
        return [self.nodes[k] for k in self.order if self.nodes[k].kind == kind]

    def get(self, key: str) -> Node:
        return self.nodes[key]

    def to_dict(self) -> dict:
        return {"trade_date": self.trade_date,
                "nodes": [{"kind": n.kind, "key": n.key, "refs": n.refs, "data": n.data}
                          for n in (self.nodes[k] for k in self.order)]}
