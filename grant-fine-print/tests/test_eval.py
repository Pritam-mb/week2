"""Tests for src.eval (PRD section 8.5 metrics).

Fixtures are written under tests/fixtures/ by the `fixtures` pytest fixture
and removed again afterwards, so the test is self-cleaning.
"""

import csv
import json
import shutil
from pathlib import Path

import pytest

from src.eval import (
    compare_systems,
    evaluate_system,
    load_labels,
    load_predictions,
    main,
    run_evaluation,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
LABELS_CSV = FIXTURES_DIR / "labels.csv"
PRED_DIR = FIXTURES_DIR / "predictions"

LABELS_HEADER = [
    "opportunity_id",
    "profile_id",
    "true_verdict",
    "disqualifying_sentence",
    "source_text",
]

# 4 labelled pairs across 4 opportunities.
LABEL_ROWS = [
    # o1/p1: ELIGIBLE; source contains the sentence sys_b quotes.
    [
        "o1",
        "p1",
        "ELIGIBLE",
        "",
        "Only U.S.-based organizations are eligible. Award ceiling is $500000.",
    ],
    # o2/p2: NOT_ELIGIBLE with a verbatim disqualifying sentence.
    [
        "o2",
        "p2",
        "NOT_ELIGIBLE",
        "For-profit organizations are not eligible to apply.",
        "For-profit organizations are not eligible to apply. Only nonprofits may apply.",
    ],
    # o3/p3: CHECK; source does NOT contain "Foreign entities are excluded."
    [
        "o3",
        "p3",
        "CHECK",
        "",
        "Applicants must be located in the rural district. Awards are limited to $10000.",
    ],
    # o4/p4: ELIGIBLE.
    [
        "o4",
        "p4",
        "ELIGIBLE",
        "",
        "Open to all applicant types. No restrictions apply.",
    ],
]


def _row(opp, profile, verdict, dq=None, cq=None, latency=None):
    row = {
        "opportunity_id": opp,
        "profile_id": profile,
        "verdict": verdict,
        "disqualifying_quotes": dq or [],
        "check_quotes": cq or [],
        "conditions": [],
        "override": None,
    }
    if latency is not None:
        row["latency_ms"] = latency
    return row


# sys_a: 3 rows (o4/p4 missing from predictions), one verbatim + one
# non-verbatim quote, latency present.
SYS_A_ROWS = [
    _row("o1", "p1", "ELIGIBLE", latency=100),
    _row(
        "o2",
        "p2",
        "NOT_ELIGIBLE",
        dq=["For-profit organizations are not eligible to apply."],
        latency=200,
    ),
    _row(
        "o3",
        "p3",
        "NOT_ELIGIBLE",
        dq=["Foreign entities are excluded."],
        latency=300,
    ),
]

# sys_b: 5 rows (o5/p5 not in labels), all quotes verbatim, no latency_ms.
SYS_B_ROWS = [
    _row(
        "o1",
        "p1",
        "NOT_ELIGIBLE",
        dq=["Only U.S.-based organizations are eligible."],
    ),
    _row(
        "o2",
        "p2",
        "NOT_ELIGIBLE",
        dq=["For-profit organizations are not eligible to apply."],
    ),
    _row(
        "o3",
        "p3",
        "CHECK",
        cq=["Applicants must be located in the rural district."],
    ),
    _row("o4", "p4", "ELIGIBLE"),
    _row("o5", "p5", "ELIGIBLE"),
]


@pytest.fixture()
def fixtures():
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    with open(LABELS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(LABELS_HEADER)
        writer.writerows(LABEL_ROWS)
    for name, rows in (("sys_a", SYS_A_ROWS), ("sys_b", SYS_B_ROWS)):
        with open(PRED_DIR / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
    yield
    shutil.rmtree(FIXTURES_DIR, ignore_errors=True)


def _kn(k, n):
    return {"k": k, "n": n, "rate": (k / n) if n else None}


def test_sys_a_metrics(fixtures):
    labels = load_labels(LABELS_CSV)
    rows = load_predictions(PRED_DIR / "sys_a.jsonl")
    m = evaluate_system(rows, labels, config={})

    assert m["n_pairs"] == 3
    assert m["n_labels"] == 4
    assert m["missed_grant_rate"] == _kn(0, 1)
    assert m["soft_miss"] == _kn(1, 1)
    assert m["human_read_share"] == _kn(0, 3)
    assert m["accuracy"] == _kn(2, 3)
    assert m["automatic_decision_coverage"] == _kn(3, 3)
    assert m["automatic_decision_accuracy"] == _kn(2, 3)
    assert m["disqualified_to_eligible_error"] == _kn(0, 1)
    assert m["negative_to_eligible_error"] == _kn(0, 2)
    assert m["confusion_matrix"] == {
        "ELIGIBLE": {"ELIGIBLE": 1, "NOT_ELIGIBLE": 0, "CHECK": 0},
        "NOT_ELIGIBLE": {"ELIGIBLE": 0, "NOT_ELIGIBLE": 1, "CHECK": 0},
        "CHECK": {"ELIGIBLE": 0, "NOT_ELIGIBLE": 1, "CHECK": 0},
    }
    # One verbatim quote (o2), one not (o3).
    assert m["quote_validity"] == _kn(1, 2)
    # Two NOT_ELIGIBLE predictions (o2, o3); o3's label is CHECK with no
    # disqualifying sentence, so only o2 can match.
    assert m["quote_correctness"] == _kn(1, 2)
    assert m["latency_ms"]["median_ms"] == 200
    assert m["latency_ms"]["p95_ms"] == pytest.approx(290)
    assert m["missing_pairs"] == [
        {"opportunity_id": "o4", "profile_id": "p4", "where": "labels_only"}
    ]


def test_sys_b_metrics(fixtures):
    labels = load_labels(LABELS_CSV)
    rows = load_predictions(PRED_DIR / "sys_b.jsonl")
    m = evaluate_system(rows, labels, config={})

    assert m["n_pairs"] == 4
    assert m["n_labels"] == 4
    assert m["missed_grant_rate"] == _kn(1, 2)
    assert m["soft_miss"] == _kn(0, 1)
    assert m["human_read_share"] == _kn(1, 4)
    assert m["accuracy"] == _kn(3, 4)
    assert m["automatic_decision_coverage"] == _kn(3, 4)
    assert m["automatic_decision_accuracy"] == _kn(2, 3)
    assert m["disqualified_to_eligible_error"] == _kn(0, 1)
    assert m["negative_to_eligible_error"] == _kn(0, 2)
    assert m["confusion_matrix"] == {
        "ELIGIBLE": {"ELIGIBLE": 1, "NOT_ELIGIBLE": 1, "CHECK": 0},
        "NOT_ELIGIBLE": {"ELIGIBLE": 0, "NOT_ELIGIBLE": 1, "CHECK": 0},
        "CHECK": {"ELIGIBLE": 0, "NOT_ELIGIBLE": 0, "CHECK": 1},
    }
    # Both quotes verbatim substrings of their opportunity source_text.
    assert m["quote_validity"] == _kn(2, 2)
    # o1's label has no disqualifying sentence, so only o2 can match.
    assert m["quote_correctness"] == _kn(1, 2)
    assert m["latency_ms"]["median_ms"] is None
    assert m["latency_ms"]["p95_ms"] is None
    assert "note" in m["latency_ms"]
    assert m["missing_pairs"] == [
        {"opportunity_id": "o5", "profile_id": "p5", "where": "predictions_only"}
    ]


def test_compare_systems(fixtures):
    results = run_evaluation(LABELS_CSV, PRED_DIR, config={})
    comp = compare_systems(results)
    # sys_a: missed 0/1 = 0.0; sys_b: 1/2 = 0.5.
    assert comp["best_missed_grant"]["system"] == "sys_a"
    # Tradeoff score = missed + human_read: sys_a 0.0 + 0.0 = 0.0.
    assert comp["best_tradeoff"]["system"] == "sys_a"
    assert comp["best_tradeoff"]["tradeoff_score"] == pytest.approx(0.0)


def test_selective_metrics_do_not_reward_always_abstaining(fixtures):
    labels = load_labels(LABELS_CSV)
    rows = [_row(opp, profile, "CHECK") for opp, profile in labels]
    metrics = evaluate_system(rows, labels, config={})
    assert metrics["automatic_decision_coverage"] == _kn(0, 4)
    assert metrics["automatic_decision_accuracy"] == _kn(0, 0)
    assert metrics["disqualified_to_eligible_error"] == _kn(0, 1)
    assert metrics["negative_to_eligible_error"] == _kn(0, 2)


def test_selective_metrics_include_ambiguous_eligibility_errors(fixtures):
    labels = load_labels(LABELS_CSV)
    rows = [_row(opp, profile, "ELIGIBLE") for opp, profile in labels]
    metrics = evaluate_system(rows, labels, config={})
    assert metrics["automatic_decision_coverage"] == _kn(4, 4)
    assert metrics["automatic_decision_accuracy"] == _kn(2, 4)
    assert metrics["disqualified_to_eligible_error"] == _kn(1, 1)
    assert metrics["negative_to_eligible_error"] == _kn(2, 2)


def test_selective_metrics_with_no_scored_pairs():
    metrics = evaluate_system([], {}, config={})
    for name in ("automatic_decision_coverage", "automatic_decision_accuracy",
                 "disqualified_to_eligible_error", "negative_to_eligible_error"):
        assert metrics[name] == _kn(0, 0)


def test_quote_validity_without_source_text(fixtures, tmp_path):
    plain = tmp_path / "labels_plain.csv"
    with open(plain, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(LABELS_HEADER[:4])
        for row in LABEL_ROWS:
            writer.writerow(row[:4])
    labels = load_labels(plain)
    rows = load_predictions(PRED_DIR / "sys_a.jsonl")
    m = evaluate_system(rows, labels, config={})
    assert m["quote_validity"]["rate"] is None
    assert m["quote_validity"]["k"] is None
    assert "source_text" in m["quote_validity"]["note"]


def test_missing_labels_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="labels file not found"):
        load_labels(tmp_path / "nope.csv")


def test_missing_predictions_dir_raises(fixtures, tmp_path):
    with pytest.raises(FileNotFoundError, match="predictions directory not found"):
        run_evaluation(LABELS_CSV, tmp_path / "nope", config={})


def test_empty_predictions_dir_raises(fixtures, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="no <system>.jsonl"):
        run_evaluation(LABELS_CSV, empty, config={})


def test_invalid_verdict_raises(tmp_path):
    bad = tmp_path / "bad_labels.csv"
    bad.write_text(
        "opportunity_id,profile_id,true_verdict,disqualifying_sentence\n"
        "o1,p1,MAYBE,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid true_verdict"):
        load_labels(bad)


def test_missing_label_column_raises(tmp_path):
    bad = tmp_path / "bad_labels.csv"
    bad.write_text("opportunity_id,profile_id\no1,p1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        load_labels(bad)


def test_cli_writes_outputs_and_is_idempotent(fixtures, tmp_path):
    out = tmp_path / "eval.json"
    report = tmp_path / "eval_report.html"
    cli_args = [
        "--labels",
        str(LABELS_CSV),
        "--predictions-dir",
        str(PRED_DIR),
        "--out",
        str(out),
        "--report",
        str(report),
    ]
    assert main(cli_args) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data["systems"]) == {"sys_a", "sys_b"}
    assert data["systems"]["sys_a"]["accuracy"] == _kn(2, 3)
    report_text = report.read_text(encoding="utf-8")
    assert "sys_a" in report_text
    assert "sys_b" in report_text
    assert "<html" in report_text

    out2 = tmp_path / "eval2.json"
    report2 = tmp_path / "eval_report2.html"
    main(
        cli_args[:-2] + ["--out", str(out2), "--report", str(report2)]
    )
    assert out.read_bytes() == out2.read_bytes()
    assert report.read_bytes() == report2.read_bytes()


def test_cli_missing_labels_exits_nonzero(tmp_path):
    rc = main(
        [
            "--labels",
            str(tmp_path / "nope.csv"),
            "--predictions-dir",
            str(PRED_DIR),
            "--out",
            str(tmp_path / "eval.json"),
        ]
    )
    assert rc == 1
