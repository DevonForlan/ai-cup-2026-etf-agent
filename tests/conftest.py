import copy
import dataclasses
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.config import load_strategy  # noqa: E402
from agent.data.loaders import load_fixture_store  # noqa: E402
from agent.engine.rules import RuleBook, load_rulebook  # noqa: E402
from agent.engine.validate_dplan import ValidationContext  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def rb() -> RuleBook:
    return load_rulebook()


@pytest.fixture(scope="session")
def cfg() -> dict:
    return load_strategy()


@pytest.fixture
def relaxed_rb(rb) -> RuleBook:
    """TEST-ONLY rulebook for tiny golden fixtures (1+ holdings, cash up to 100%)."""
    r = dataclasses.replace(rb.rules, holdings_min=1, cash_max_weight=Decimal(1))
    return RuleBook(r, rb.universe, rb.active_etfs, rb.assumptions)


@pytest.fixture
def golden_rb(rb) -> RuleBook:
    """TEST-ONLY rulebook for the hand-calculated golden test (also no weight caps)."""
    r = dataclasses.replace(rb.rules, holdings_min=1, cash_max_weight=Decimal(1),
                            other_max_weight=Decimal(1), tsmc_max_weight=Decimal(1))
    return RuleBook(r, rb.universe, rb.active_etfs, rb.assumptions)


@pytest.fixture(scope="session")
def fixture_store(tmp_path_factory):
    return load_fixture_store(FIXTURES / "synthetic", tmp_path_factory.mktemp("fxstore"))


def load_example(team: str) -> dict:
    return json.loads((ROOT / f"D-Plan_TEAM_{team}_2026-10-27.json").read_text(encoding="utf-8"))


def example_ctx(team: str = "042", **kw) -> ValidationContext:
    ctx = ValidationContext.from_json(FIXTURES / f"ex_context_{team}.json")
    ctx.filename = f"D-Plan_TEAM_{team}_2026-10-27.json"
    for k, v in kw.items():
        setattr(ctx, k, v)
    return ctx


@pytest.fixture
def ex42():
    return copy.deepcopy(load_example("042"))


@pytest.fixture
def ex43():
    return copy.deepcopy(load_example("043"))
