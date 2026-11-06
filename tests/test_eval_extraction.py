"""Tests for scripts/eval_extraction.py (Lite-Mem extraction accuracy evaluation)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def ev():
    path = ROOT / "scripts" / "eval_extraction.py"
    spec = importlib.util.spec_from_file_location("_eval_extraction", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses resolve their module via sys.modules
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def test_wilson_interval_matches_closed_form(ev):
    lo, hi = ev.wilson(8, 16)
    assert lo == pytest.approx(0.280, abs=1e-3)
    assert hi == pytest.approx(0.720, abs=1e-3)
    assert ev.wilson(0, 0) is None
    lo, hi = ev.wilson(0, 10)
    assert lo == 0.0 and 0.0 < hi < 0.35


def test_prf_edge_cases(ev):
    assert ev.prf(0, 0, 5) == {"precision": None, "recall": 0.0, "f1": None}
    m = ev.prf(8, 8, 21)
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(8 / 29)


def test_sample_is_deterministic_and_unique(ev):
    pool = ev.build_pool()
    first = [s.sample_id for s in ev.draw_sample(pool)]
    second = [s.sample_id for s in ev.draw_sample(ev.build_pool())]
    assert first == second
    assert len(first) == ev.SAMPLE_SIZE == len(set(first))


def test_production_path_replays_stub_extractor(ev):
    sample = ev.Sample("t-0", "test", 1001, "ds101", "我完全不懂鏈結串列", "好，從頭開始。")
    res = ev.run_production_path(sample)
    assert res.user_content == "[資料結構] 我完全不懂鏈結串列"
    assert not res.via_fallback
    assert {"text": "不懂鏈結串列", "category": "learning"} in res.facts


def test_labels_file_reproduces_reported_numbers(ev):
    rep = ev.score(ev.DEFAULT_LABELS)  # also fails if the extractor output drifted
    assert rep["n_messages"] == 50
    assert (rep["strict"]["tp"], rep["strict"]["fp"], rep["strict"]["fn"]) == (8, 8, 21)
    assert (rep["lenient"]["tp"], rep["lenient"]["fp"], rep["lenient"]["fn"]) == (9, 7, 20)
    assert rep["struggle_on_dashboard"]["tp"] == 14
    assert rep["struggle_on_dashboard"]["fp"] == 1


def test_match_column_validation(ev):
    with pytest.raises(ValueError, match="at most one"):
        ev._parse_matches("g1;g1", 2, {"g1"}, "x")
    with pytest.raises(ValueError, match="expected 2"):
        ev._parse_matches("g1", 2, {"g1"}, "x")
    with pytest.raises(ValueError, match="unknown gold id"):
        ev._parse_matches("g9", 1, {"g1"}, "x")
