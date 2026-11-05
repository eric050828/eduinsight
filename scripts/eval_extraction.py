"""Evaluate Lite-Mem fact extraction on demo student messages (P / R / F1).

What is evaluated is the *production* path, not the pre-written demo facts:

    /chat (LLM configured) -> LearningAssistant.answer()
        -> LearningAssistant.extract_from_conversation()
        -> Memory.add_conversation(uid, [user, assistant], extractor="stub")
        -> litemem StubExtractor (rule-based, offline)
    if no fact comes back -> LearningAssistant.record_interaction()  ("[topic] Q: ..." / "A: ...")

The student UI sends ``topic=<course name>`` so the user turn is ``"[資料結構] <question>"``.
This script replays each sampled student message through exactly those methods on a
throw-away in-memory ``Memory`` (embedder disabled: embeddings do not change which facts
are extracted), then runs ``analytics.analyze_student`` on what was stored.

Usage::

    # 1. build an (unlabelled) annotation sheet for the fixed 50-message sample
    uv run python scripts/eval_extraction.py sheet --out eval/new_sheet.csv

    # 2. score a labelled sheet (re-runs the extractor and checks it still matches)
    uv run python scripts/eval_extraction.py score eval/extraction_labels_2026-11-04.csv

Annotation columns filled by the annotator (see docs/LITEMEM-EXTRACTION-ACCURACY.md):
    gold_facts      JSON list: [{"id": "g1", "type": "struggle|affect|preference|context",
                                 "topic": "...", "desc": "..."}]
    gold_struggle   1 if the message shows a learning difficulty, else 0
    match_strict    one entry per extracted fact, ";"-separated: gold id or "-"
    match_lenient   same, under the lenient criterion
    notes           free-text rationale
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from litemem import Memory

from eduinsight.analytics import _is_natural_struggle, analyze_student
from eduinsight.assistant import LearningAssistant
from eduinsight.courses import COURSE_CATALOG
from eduinsight.demo_conversations import DEMO_CONVERSATIONS

ROOT = Path(__file__).resolve().parent.parent
SEED = 20261104
SAMPLE_SIZE = 50
DEFAULT_LABELS = ROOT / "eval" / "extraction_labels_2026-11-04.csv"
GOLD_TYPES = ("struggle", "affect", "preference", "context")

SHEET_FIELDS = [
    "sample_id", "source", "student", "course", "user_content",
    "extracted_facts", "stored_via_fallback", "analytics_struggles",
    "gold_facts", "gold_struggle", "match_strict", "match_lenient", "notes",
]


@dataclass(frozen=True)
class Sample:
    sample_id: str
    source: str
    student: int
    course: str  # course id, "" when the source has none
    question: str
    answer: str

    @property
    def topic(self) -> str:
        """What the student UI sends as ChatRequest.topic (course display name)."""
        return COURSE_CATALOG.get(self.course, self.course) if self.course else ""


# ----------------------------------------------------------------------
# Corpus
# ----------------------------------------------------------------------

def _load_semester_script():
    path = ROOT / "scripts" / "seed_semester_conversations.py"
    spec = importlib.util.spec_from_file_location("_seed_semester_conversations", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def build_pool() -> list[Sample]:
    """Every student turn in the demo conversation sources, with a stable id."""
    sem = _load_semester_script()
    pool: list[Sample] = []
    for i, t in enumerate(sem.CONVERSATIONS):
        pool.append(Sample(f"sem-{i:03d}", "seed_semester_conversations.CONVERSATIONS",
                           t.student, t.course, t.question, t.answer))
    for i, s in enumerate(sem.MULTITURN_SESSIONS):
        for j, (q, a) in enumerate(s.turns):
            pool.append(Sample(f"mt-{i}-{j}", "seed_semester_conversations.MULTITURN_SESSIONS",
                               s.student, s.course, q, a))
    for uid, sessions in DEMO_CONVERSATIONS.items():
        student = int(uid.removeprefix("moodle:"))
        for session_id, turns in sessions:
            for j, (role, content) in enumerate(turns):
                if role != "user":
                    continue
                reply = next((c for r, c in turns[j + 1:] if r == "assistant"), "")
                pool.append(Sample(f"{session_id}-{j}", "demo_conversations.DEMO_CONVERSATIONS",
                                   student, "", content, reply))
    ids = [s.sample_id for s in pool]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate sample ids in pool")
    return pool


def draw_sample(pool: list[Sample], n: int = SAMPLE_SIZE, seed: int = SEED) -> list[Sample]:
    ordered = sorted(pool, key=lambda s: s.sample_id)
    picked = random.Random(seed).sample(ordered, n)
    return sorted(picked, key=lambda s: s.sample_id)


# ----------------------------------------------------------------------
# Running the production extraction path
# ----------------------------------------------------------------------

@dataclass
class RunResult:
    user_content: str
    facts: list[dict[str, str]]  # [{"text", "category"}] as stored by Lite-Mem
    via_fallback: bool
    analytics_struggles: list[str]  # "topic | details" per analytics Struggle
    stored_texts: list[str]


def run_production_path(sample: Sample) -> RunResult:
    memory = Memory(":memory:", embedder=None)
    assistant = LearningAssistant(memory)  # extractor defaults to "stub", as in app.py
    facts = assistant.extract_from_conversation(
        sample.student, sample.question, sample.answer, topic=sample.topic
    )
    uid = f"moodle:{sample.student}"
    stored = memory.list_facts(uid)
    fact_rows = [{"text": r["text"], "category": r["category"]} for r in stored]
    if not facts:
        assistant.record_interaction(sample.student, sample.question, sample.answer,
                                     topic=sample.topic)
    analytics = analyze_student(memory, sample.student)
    stored_texts = memory.list(uid)
    memory.close()
    user_content = f"[{sample.topic}] {sample.question}" if sample.topic else sample.question
    return RunResult(
        user_content=user_content,
        facts=fact_rows,
        via_fallback=not facts,
        analytics_struggles=[f"{s.topic} | {s.details}" for s in analytics.struggles],
        stored_texts=stored_texts,
    )


# ----------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------

def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion (95% by default)."""
    if total == 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"precision": p, "recall": r, "f1": f}


def bootstrap_f1(per_sample: list[tuple[int, int, int]], *, reps: int = 2000,
                 seed: int = SEED) -> tuple[float, float] | None:
    """Percentile bootstrap (resampling messages) for micro F1."""
    rng = random.Random(seed)
    n = len(per_sample)
    values: list[float] = []
    for _ in range(reps):
        tp = fp = fn = 0
        for _ in range(n):
            a, b, c = per_sample[rng.randrange(n)]
            tp, fp, fn = tp + a, fp + b, fn + c
        f = prf(tp, fp, fn)["f1"]
        values.append(f if f is not None else 0.0)
    values.sort()
    return values[int(0.025 * reps)], values[int(0.975 * reps) - 1]


# ----------------------------------------------------------------------
# Sheet I/O
# ----------------------------------------------------------------------

def write_sheet(samples: list[Sample], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        for s in samples:
            res = run_production_path(s)
            writer.writerow({
                "sample_id": s.sample_id,
                "source": s.source,
                "student": s.student,
                "course": s.course,
                "user_content": res.user_content,
                "extracted_facts": json.dumps(res.facts, ensure_ascii=False),
                "stored_via_fallback": int(res.via_fallback),
                "analytics_struggles": json.dumps(res.analytics_struggles, ensure_ascii=False),
                "gold_facts": "[]",
                "gold_struggle": "",
                "match_strict": "",
                "match_lenient": "",
                "notes": "",
            })


def read_sheet(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _parse_matches(raw: str, n_facts: int, gold_ids: set[str], where: str) -> list[str]:
    parts = [p.strip() for p in raw.split(";")] if raw.strip() else []
    if len(parts) != n_facts:
        raise ValueError(f"{where}: expected {n_facts} match entries, got {len(parts)}")
    matched = [p for p in parts if p != "-"]
    for p in matched:
        if p not in gold_ids:
            raise ValueError(f"{where}: unknown gold id {p!r}")
    if len(matched) != len(set(matched)):
        raise ValueError(f"{where}: a gold fact may be matched by at most one extracted fact")
    return parts


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------

def score(path: Path, *, check_drift: bool = True) -> dict:
    rows = read_sheet(path)
    if check_drift:
        expected = {s.sample_id: s for s in draw_sample(build_pool())}
        if [r["sample_id"] for r in rows] != sorted(expected):
            raise ValueError("sheet sample ids differ from the seeded sample")
        for r in rows:
            live = run_production_path(expected[r["sample_id"]])
            if json.loads(r["extracted_facts"]) != live.facts:
                raise ValueError(f"{r['sample_id']}: extractor output drifted from the sheet; "
                                 "re-label before trusting the numbers")
            if json.loads(r["analytics_struggles"]) != live.analytics_struggles:
                raise ValueError(f"{r['sample_id']}: analytics output drifted from the sheet")

    report: dict = {"n_messages": len(rows)}
    for mode in ("strict", "lenient"):
        tp = fp = fn = 0
        per_sample: list[tuple[int, int, int]] = []
        by_gold_type = {t: [0, 0] for t in GOLD_TYPES}  # [matched, total]
        by_pred_cat: dict[str, list[int]] = {}  # category -> [tp, extracted]
        for r in rows:
            facts = json.loads(r["extracted_facts"])
            gold = json.loads(r["gold_facts"])
            gold_ids = {g["id"] for g in gold}
            matches = _parse_matches(r[f"match_{mode}"], len(facts), gold_ids,
                                     f"{r['sample_id']} match_{mode}")
            hit = {m for m in matches if m != "-"}
            s_tp, s_fp, s_fn = len(hit), len(facts) - len(hit), len(gold) - len(hit)
            tp, fp, fn = tp + s_tp, fp + s_fp, fn + s_fn
            per_sample.append((s_tp, s_fp, s_fn))
            for g in gold:
                if g["type"] not in GOLD_TYPES:
                    raise ValueError(f"{r['sample_id']}: bad gold type {g['type']!r}")
                by_gold_type[g["type"]][1] += 1
                by_gold_type[g["type"]][0] += g["id"] in hit
            for fact, m in zip(facts, matches):
                slot = by_pred_cat.setdefault(fact["category"], [0, 0])
                slot[1] += 1
                slot[0] += m != "-"
        metrics = prf(tp, fp, fn)
        report[mode] = {
            "tp": tp, "fp": fp, "fn": fn, **metrics,
            "precision_ci": wilson(tp, tp + fp),
            "recall_ci": wilson(tp, tp + fn),
            "f1_bootstrap_ci": bootstrap_f1(per_sample),
            "recall_by_gold_type": {
                t: {"matched": m, "total": n, "recall": (m / n if n else None),
                    "ci": wilson(m, n)}
                for t, (m, n) in by_gold_type.items()
            },
            "precision_by_litemem_category": {
                c: {"tp": a, "extracted": b, "precision": a / b, "ci": wilson(a, b)}
                for c, (a, b) in sorted(by_pred_cat.items())
            },
        }

    # Message-level struggle detection (binary), two system definitions.
    def binary(pred: list[bool]) -> dict:
        gold = [r["gold_struggle"].strip() == "1" for r in rows]
        tp = sum(p and g for p, g in zip(pred, gold))
        fp = sum(p and not g for p, g in zip(pred, gold))
        fn = sum(g and not p for p, g in zip(pred, gold))
        tn = sum(not p and not g for p, g in zip(pred, gold))
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, **prf(tp, fp, fn),
                "precision_ci": wilson(tp, tp + fp), "recall_ci": wilson(tp, tp + fn),
                "gold_positive": sum(gold)}

    memory_signal = [any(_is_natural_struggle(f["text"]) for f in json.loads(r["extracted_facts"]))
                     for r in rows]
    dashboard = [bool(json.loads(r["analytics_struggles"])) for r in rows]
    report["struggle_in_extracted_facts"] = binary(memory_signal)
    report["struggle_on_dashboard"] = binary(dashboard)
    report["messages_with_any_fact"] = sum(bool(json.loads(r["extracted_facts"])) for r in rows)
    report["messages_via_fallback"] = sum(r["stored_via_fallback"] == "1" for r in rows)
    report["extracted_facts_total"] = sum(len(json.loads(r["extracted_facts"])) for r in rows)
    report["gold_facts_total"] = sum(len(json.loads(r["gold_facts"])) for r in rows)
    return report


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _fmt_ci(ci: tuple[float, float] | None) -> str:
    return "n/a" if ci is None else f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def print_report(rep: dict) -> None:
    print(f"messages: {rep['n_messages']}  with >=1 extracted fact: "
          f"{rep['messages_with_any_fact']}  via Q/A fallback: {rep['messages_via_fallback']}")
    print(f"extracted facts: {rep['extracted_facts_total']}  gold facts: "
          f"{rep['gold_facts_total']}\n")
    for mode in ("strict", "lenient"):
        m = rep[mode]
        print(f"[fact-level, {mode}] TP={m['tp']} FP={m['fp']} FN={m['fn']}")
        print(f"  precision {_fmt(m['precision'])} 95% Wilson {_fmt_ci(m['precision_ci'])}")
        print(f"  recall    {_fmt(m['recall'])} 95% Wilson {_fmt_ci(m['recall_ci'])}")
        print(f"  F1        {_fmt(m['f1'])} 95% bootstrap {_fmt_ci(m['f1_bootstrap_ci'])}")
        for t, v in m["recall_by_gold_type"].items():
            print(f"    recall[{t}] {v['matched']}/{v['total']} = {_fmt(v['recall'])} "
                  f"{_fmt_ci(v['ci'])}")
        for c, v in m["precision_by_litemem_category"].items():
            print(f"    precision[litemem:{c}] {v['tp']}/{v['extracted']} = "
                  f"{_fmt(v['precision'])} {_fmt_ci(v['ci'])}")
        print()
    for key, label in (("struggle_in_extracted_facts", "struggle signal in extracted facts"),
                       ("struggle_on_dashboard", "struggle counted by analyze_student")):
        b = rep[key]
        print(f"[message-level, {label}] gold+={b['gold_positive']} TP={b['tp']} "
              f"FP={b['fp']} FN={b['fn']} TN={b['tn']}")
        print(f"  precision {_fmt(b['precision'])} {_fmt_ci(b['precision_ci'])}  "
              f"recall {_fmt(b['recall'])} {_fmt_ci(b['recall_ci'])}  F1 {_fmt(b['f1'])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_sheet = sub.add_parser("sheet", help="write an unlabelled annotation sheet")
    p_sheet.add_argument("--out", type=Path, required=True)
    p_score = sub.add_parser("score", help="score a labelled sheet")
    p_score.add_argument("labels", type=Path, nargs="?", default=DEFAULT_LABELS)
    p_score.add_argument("--json", action="store_true", help="print raw JSON")
    p_score.add_argument("--no-drift-check", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "sheet":
        pool = build_pool()
        write_sheet(draw_sample(pool), args.out)
        print(f"pool={len(pool)} sampled={SAMPLE_SIZE} seed={SEED} -> {args.out}")
        return 0
    rep = score(args.labels, check_drift=not args.no_drift_check)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print_report(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
