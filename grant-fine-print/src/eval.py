"""Evaluation metrics for Grant Fine Print (PRD section 8.5).

All metrics are computed here and nowhere else: never compute them by hand.

Inputs
------
Labels CSV (required columns): opportunity_id, profile_id, true_verdict,
disqualifying_sentence. Optional column: source_text (the opportunity's
source text; required for quote_validity).

Predictions: one JSONL file per system in the predictions directory, named
<system>.jsonl, each line a VerdictRow dict as produced by
VerdictRow.to_dict(). An optional numeric latency_ms field per row enables
the latency metrics.

Config: config.yaml (read with PyYAML, already a project dependency).
Only config["eval"]["cost_per_opportunity"] is consulted, for cost; if
absent, cost is reported as null with a note (prices are never invented).

Stdlib only for metrics and reporting; the HTML report is pure HTML/CSS.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Optional

from .models import normalize_ws
from .verify import is_verbatim_quote

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a project dependency
    yaml = None  # type: ignore[assignment]

VERDICTS = ("ELIGIBLE", "NOT_ELIGIBLE", "CHECK")

REQUIRED_LABEL_COLUMNS = (
    "opportunity_id",
    "profile_id",
    "true_verdict",
    "disqualifying_sentence",
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_config(path: Path) -> dict:
    """Load config.yaml (PyYAML is a hard project dependency)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    if yaml is None:  # pragma: no cover
        raise RuntimeError("PyYAML is required to read config.yaml")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def get(config: dict, *keys: str, default: Any = None) -> Any:
    """Nested dict lookup: get(config, "eval", "labels_path")."""
    node: Any = config
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def load_labels(path: Path) -> dict:
    """Load the frozen labels CSV.

    Returns {(opportunity_id, profile_id): {true_verdict,
    disqualifying_sentence, source_text}}.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"labels file not found: {path}")
    labels: dict[tuple[str, str], dict] = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        missing = [c for c in REQUIRED_LABEL_COLUMNS if c not in fieldnames]
        if missing:
            raise ValueError(
                f"labels CSV {path} is missing required columns: "
                + ", ".join(missing)
            )
        for line_no, row in enumerate(reader, start=2):
            key = (row["opportunity_id"].strip(), row["profile_id"].strip())
            verdict = (row["true_verdict"] or "").strip()
            if verdict not in VERDICTS:
                raise ValueError(
                    f"labels CSV {path} line {line_no}: invalid "
                    f"true_verdict {verdict!r} for pair {key}"
                )
            labels[key] = {
                "true_verdict": verdict,
                "disqualifying_sentence": row.get("disqualifying_sentence") or "",
                "source_text": row.get("source_text") or "",
            }
    if not labels:
        raise ValueError(f"labels CSV {path} contains no rows")
    return labels


def load_predictions(path: Path) -> list[dict]:
    """Load one system's predictions JSONL (VerdictRow dicts per line)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"predictions file not found: {path}")
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"predictions file {path} line {line_no}: invalid JSON: {exc}"
                )
            if not isinstance(row, dict):
                raise ValueError(
                    f"predictions file {path} line {line_no}: line is not a JSON object"
                )
            for field in ("opportunity_id", "profile_id", "verdict"):
                if field not in row:
                    raise ValueError(
                        f"predictions file {path} line {line_no}: missing {field!r}"
                    )
            if row["verdict"] not in VERDICTS:
                raise ValueError(
                    f"predictions file {path} line {line_no}: invalid "
                    f"verdict {row['verdict']!r}"
                )
            rows.append(row)
    if not rows:
        raise ValueError(f"predictions file {path} contains no rows")
    return rows


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------


def _kn(k: int, n: int) -> dict:
    """Raw 'k of N' count plus the rate (null when N is 0)."""
    return {"k": k, "n": n, "rate": (k / n) if n else None}


def percentile(values: list[float], p: float) -> Optional[float]:
    """Percentile with linear interpolation on the sorted sample.

    Deterministic: index = (n - 1) * p, interpolate between neighbours.
    Returns None for an empty sample.
    """
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    idx = (len(ordered) - 1) * p
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return ordered[int(idx)]
    frac = idx - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------


def evaluate_system(rows: list[dict], labels: dict, config: dict) -> dict:
    """Compute every PRD 8.5 metric for one system.

    rows: VerdictRow dicts from one <system>.jsonl file.
    labels: output of load_labels.
    config: loaded config (only eval.cost_per_opportunity is consulted).

    Pairs are matched on (opportunity_id, profile_id). Only pairs present in
    both predictions and labels are scored; the rest are reported in
    missing_pairs. If a pair is predicted more than once, the first row
    wins (deterministic).
    """
    label_keys = set(labels)
    seen: set[tuple[str, str]] = set()
    scored: list[dict] = []
    for row in rows:
        key = (row["opportunity_id"], row["profile_id"])
        if key in label_keys and key not in seen:
            seen.add(key)
            scored.append(row)

    pred_keys = {(row["opportunity_id"], row["profile_id"]) for row in rows}
    missing_pairs = [
        {
            "opportunity_id": key[0],
            "profile_id": key[1],
            "where": "labels_only",
        }
        for key in sorted(label_keys - pred_keys)
    ] + [
        {
            "opportunity_id": key[0],
            "profile_id": key[1],
            "where": "predictions_only",
        }
        for key in sorted(pred_keys - label_keys)
    ]

    n = len(scored)
    confusion = {t: {p: 0 for p in VERDICTS} for t in VERDICTS}
    n_eligible = n_check = n_missed = n_soft = n_human = n_correct = 0

    for row in scored:
        key = (row["opportunity_id"], row["profile_id"])
        truth = labels[key]["true_verdict"]
        pred = row["verdict"]
        confusion[truth][pred] += 1
        if truth == "ELIGIBLE":
            n_eligible += 1
            if pred == "NOT_ELIGIBLE":
                n_missed += 1
        if truth == "CHECK":
            n_check += 1
            if pred == "NOT_ELIGIBLE":
                n_soft += 1
        if pred == "CHECK":
            n_human += 1
        if truth == pred:
            n_correct += 1

    # Quote validity: share of model-proposed disqualifier quotes that are
    # verbatim substrings of the opportunity source_text (needs the optional
    # source_text column in the labels CSV). When the pipeline provides
    # proposed_disqualifier_quotes (captured BEFORE quote verification), that
    # list is used so validity is measured before code enforcement; otherwise
    # it falls back to the already-enforced disqualifying_quotes.
    quotes_total = quotes_valid = 0
    any_source = False
    for row in scored:
        source = labels[(row["opportunity_id"], row["profile_id"])]["source_text"]
        if source:
            any_source = True
        quotes = row.get("proposed_disqualifier_quotes")
        if quotes is None:
            quotes = row.get("disqualifying_quotes") or []
        for quote in quotes or []:
            quotes_total += 1
            if source and is_verbatim_quote(quote, source):
                quotes_valid += 1
    if any_source:
        quote_validity: dict = _kn(quotes_valid, quotes_total)
    else:
        quote_validity = {
            "k": None,
            "n": quotes_total,
            "rate": None,
            "note": (
                "labels CSV has no source_text column; quote validity "
                "not computed"
            ),
        }

    # Quote correctness: among NOT_ELIGIBLE predictions, share whose quoted
    # sentence equals (whitespace-normalised) the label's
    # disqualifying_sentence. Label rows with an empty disqualifying
    # sentence count in the denominator but can never match.
    ne_total = ne_correct = 0
    for row in scored:
        if row["verdict"] != "NOT_ELIGIBLE":
            continue
        ne_total += 1
        key = (row["opportunity_id"], row["profile_id"])
        label_sentence = normalize_ws(labels[key]["disqualifying_sentence"])
        if not label_sentence:
            continue
        predicted = {
            normalize_ws(q) for q in row.get("disqualifying_quotes") or []
        }
        if label_sentence in predicted:
            ne_correct += 1

    latencies = [
        float(row["latency_ms"])
        for row in scored
        if isinstance(row.get("latency_ms"), (int, float))
        and not isinstance(row.get("latency_ms"), bool)
    ]
    if latencies:
        latency: dict = {
            "median_ms": statistics.median(latencies),
            "p95_ms": percentile(latencies, 0.95),
            "n": len(latencies),
        }
    else:
        latency = {
            "median_ms": None,
            "p95_ms": None,
            "note": "latency_ms absent from predictions; latency not computed",
        }

    price = get(config, "eval", "cost_per_opportunity", default=None)
    if price is None:
        cost: dict = {
            "cost_per_1000_opportunities": None,
            "note": "no list price in config; cost not computed",
        }
    else:
        cost = {
            "cost_per_1000_opportunities": float(price) * 1000.0,
            "note": f"list price {price} per opportunity from config",
        }

    return {
        "n_pairs": n,
        "n_labels": len(labels),
        "missing_pairs": missing_pairs,
        "missed_grant_rate": _kn(n_missed, n_eligible),
        "soft_miss": _kn(n_soft, n_check),
        "human_read_share": _kn(n_human, n),
        "accuracy": _kn(n_correct, n),
        "confusion_matrix": confusion,
        "quote_validity": quote_validity,
        "quote_correctness": _kn(ne_correct, ne_total),
        "latency_ms": latency,
        "cost": cost,
    }


def run_evaluation(labels_path: Path, predictions_dir: Path, config: dict) -> dict:
    """Evaluate every <system>.jsonl in predictions_dir against labels."""
    labels = load_labels(labels_path)
    predictions_dir = Path(predictions_dir)
    if not predictions_dir.is_dir():
        raise FileNotFoundError(
            f"predictions directory not found: {predictions_dir}"
        )
    systems = {}
    for pred_file in sorted(predictions_dir.glob("*.jsonl")):
        systems[pred_file.stem] = evaluate_system(
            load_predictions(pred_file), labels, config
        )
    if not systems:
        raise FileNotFoundError(
            f"no <system>.jsonl prediction files in {predictions_dir}"
        )
    results = {"systems": systems}
    results["comparison"] = compare_systems(results)
    return results


def _rate(entry: dict, metric: str) -> Optional[float]:
    value = entry[metric]["rate"]
    return float(value) if value is not None else None


def compare_systems(results: dict) -> dict:
    """Headline pair for the write-up.

    best_missed_grant: lowest missed_grant_rate (tie-break: higher
    accuracy, then system name).

    best_tradeoff: lowest missed_grant_rate + human_read_share (a missed
    grant and a human read are both costs; tie-break: higher accuracy,
    then system name). Systems with a null rate are ranked last and get a
    null tradeoff_score.
    """
    systems = results.get("systems") or {}
    if not systems:
        raise ValueError("compare_systems: results contain no systems")

    def acc_key(name: str) -> float:
        acc = _rate(systems[name], "accuracy")
        return -acc if acc is not None else math.inf

    def missed_key(name: str) -> tuple:
        missed = _rate(systems[name], "missed_grant_rate")
        return (
            missed if missed is not None else math.inf,
            acc_key(name),
            name,
        )

    def tradeoff_key(name: str) -> tuple:
        missed = _rate(systems[name], "missed_grant_rate")
        human = _rate(systems[name], "human_read_share")
        score = (
            missed + human
            if missed is not None and human is not None
            else None
        )
        return (
            score if score is not None else math.inf,
            acc_key(name),
            name,
        )

    best_missed = min(systems, key=missed_key)
    best_tradeoff = min(systems, key=tradeoff_key)
    tradeoff_missed = _rate(systems[best_tradeoff], "missed_grant_rate")
    tradeoff_human = _rate(systems[best_tradeoff], "human_read_share")
    return {
        "best_missed_grant": {
            "system": best_missed,
            "missed_grant_rate": systems[best_missed]["missed_grant_rate"],
        },
        "best_tradeoff": {
            "system": best_tradeoff,
            "tradeoff_score": (
                tradeoff_missed + tradeoff_human
                if tradeoff_missed is not None and tradeoff_human is not None
                else None
            ),
            "missed_grant_rate": systems[best_tradeoff]["missed_grant_rate"],
            "human_read_share": systems[best_tradeoff]["human_read_share"],
        },
    }


# ---------------------------------------------------------------------------
# HTML report (pure HTML/CSS, no external libs)
# ---------------------------------------------------------------------------


def _fmt_kn(entry: dict) -> str:
    if entry["k"] is None or entry["n"] is None:
        return "n/a"
    rate = entry["rate"]
    suffix = "" if rate is None else f" ({rate * 100:.1f}%)"
    return f"{entry['k']} of {entry['n']}{suffix}"


def _fmt_latency(latency: dict) -> str:
    if latency["median_ms"] is None:
        return "n/a"
    return f"median {latency['median_ms']:g} ms, p95 {latency['p95_ms']:g} ms"


def _fmt_cost(cost: dict) -> str:
    value = cost["cost_per_1000_opportunities"]
    return "n/a" if value is None else f"${value:,.2f}"


def render_report(results: dict) -> str:
    """Self-contained HTML report: inline bar charts + full metrics table."""
    systems = results.get("systems", {})
    comparison = results.get("comparison") or compare_systems(results)

    def chart(metric: str, title: str, color: str) -> str:
        parts = [f"<h2>{html.escape(title)}</h2>", '<div class="chart">']
        for name in sorted(systems):
            entry = systems[name][metric]
            rate = entry["rate"]
            width = 0.0 if rate is None else max(0.0, min(1.0, rate)) * 100.0
            label = "n/a" if rate is None else f"{entry['k']} of {entry['n']}"
            parts.append(
                '<div class="chart-row">'
                f'<span class="sys-label">{html.escape(name)}</span>'
                f'<span class="bar" style="width:{width:.1f}%;'
                f'background:{color}"></span>'
                f'<span class="bar-label">{html.escape(label)}</span>'
                "</div>"
            )
        parts.append("</div>")
        return "\n".join(parts)

    table_rows = []
    for name in sorted(systems):
        m = systems[name]
        cells = [
            html.escape(name),
            str(m["n_pairs"]),
            str(m["n_labels"]),
            _fmt_kn(m["missed_grant_rate"]),
            _fmt_kn(m["soft_miss"]),
            _fmt_kn(m["human_read_share"]),
            _fmt_kn(m["accuracy"]),
            _fmt_kn(m["quote_validity"]),
            _fmt_kn(m["quote_correctness"]),
            _fmt_latency(m["latency_ms"]),
            _fmt_cost(m["cost"]),
        ]
        table_rows.append(
            "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
        )

    best_missed = comparison["best_missed_grant"]
    best_tradeoff = comparison["best_tradeoff"]
    tradeoff_score = best_tradeoff["tradeoff_score"]
    score_text = "n/a" if tradeoff_score is None else f"{tradeoff_score:.3f}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Grant Fine Print — eval report</title>
<style>
body {{ font-family: Georgia, serif; margin: 2rem auto; max-width: 60rem;
        padding: 0 1rem; color: #222; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: .25rem; }}
h2 {{ margin-top: 2rem; }}
.chart {{ margin: 1rem 0; }}
.chart-row {{ display: flex; align-items: center; margin: .35rem 0; }}
.sys-label {{ width: 10rem; font-family: monospace; }}
.bar {{ display: inline-block; height: 1.1rem; min-width: 2px;
        vertical-align: middle; }}
.bar-label {{ margin-left: .5rem; font-family: monospace; }}
table {{ border-collapse: collapse; margin-top: 1rem; width: 100%; }}
th, td {{ border: 1px solid #999; padding: .3rem .5rem; text-align: left;
          font-size: .9rem; }}
th {{ background: #eee; }}
.headline {{ background: #f4f4f4; border: 1px solid #ccc; padding: .75rem 1rem; }}
</style>
</head>
<body>
<h1>Grant Fine Print — system comparison</h1>
<p>Metrics per PRD section 8.5, computed by <code>src/eval.py</code>.
Every metric is reported as raw &ldquo;k of N&rdquo; counts.</p>

<div class="headline">
<p><strong>Best missed-grant rate:</strong>
{html.escape(best_missed["system"])} —
{_fmt_kn(best_missed["missed_grant_rate"])}</p>
<p><strong>Best tradeoff</strong> (lowest missed-grant rate + human-read
share): {html.escape(best_tradeoff["system"])} — score {html.escape(score_text)}
({_fmt_kn(best_tradeoff["missed_grant_rate"])} missed grants,
{_fmt_kn(best_tradeoff["human_read_share"])} human reads)</p>
</div>

{chart("missed_grant_rate", "Missed-grant rate (lower is better)", "#b03a2e")}
{chart("human_read_share", "Human-read share", "#2e6da4")}

<h2>All metrics</h2>
<table>
<tr><th>system</th><th>n_pairs</th><th>n_labels</th><th>missed_grant_rate</th>
<th>soft_miss</th><th>human_read_share</th><th>accuracy</th>
<th>quote_validity</th><th>quote_correctness</th><th>latency</th>
<th>cost/1k opps</th></tr>
{''.join(table_rows)}
</table>

<h2>Metric definitions</h2>
<ul>
<li><strong>missed_grant_rate</strong> — true ELIGIBLE predicted
NOT_ELIGIBLE, k of N_eligible.</li>
<li><strong>soft_miss</strong> — true CHECK predicted NOT_ELIGIBLE,
k of N_check.</li>
<li><strong>human_read_share</strong> — pairs predicted CHECK, k of N.</li>
<li><strong>accuracy</strong> — three-way agreement, k of N.</li>
<li><strong>quote_validity</strong> — proposed disqualifier quotes that are
verbatim substrings of the opportunity source_text, k of N_quotes.</li>
<li><strong>quote_correctness</strong> — NOT_ELIGIBLE predictions whose
quote equals the label&rsquo;s disqualifying_sentence (normalised),
k of N_noteligible.</li>
<li><strong>latency</strong> — median and p95 of latency_ms per row.</li>
</ul>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.eval",
        description="Compute PRD 8.5 evaluation metrics for each system.",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="path to config.yaml (default: %(default)s)",
    )
    parser.add_argument("--labels", default=None, help="path to labels CSV")
    parser.add_argument(
        "--predictions-dir", default=None, help="directory of <system>.jsonl files"
    )
    parser.add_argument("--out", default=None, help="path to write eval.json")
    parser.add_argument(
        "--report", default=None, help="path to write the HTML report"
    )
    args = parser.parse_args(argv)

    try:
        config_path = Path(args.config)
        config = load_config(config_path)
        root = config_path.resolve().parent

        def resolve(path: Optional[str], default: Path) -> Path:
            p = Path(path) if path else root / default
            return p

        labels_path = resolve(
            args.labels, get(config, "eval", "labels_path",
                            default="data/labels/test_labels.csv")
        )
        predictions_dir = resolve(
            args.predictions_dir,
            get(config, "eval", "predictions_dir",
                default="results/predictions"),
        )
        out_path = resolve(
            args.out, get(config, "eval", "output", default="results/eval.json")
        )
        report_path = (
            Path(args.report)
            if args.report
            else out_path.parent / "eval_report.html"
        )

        results = run_evaluation(labels_path, predictions_dir, config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    report_path.write_text(render_report(results), encoding="utf-8")

    for name in sorted(results["systems"]):
        m = results["systems"][name]
        print(
            f"{name}: accuracy {_fmt_kn(m['accuracy'])}, "
            f"missed-grant {_fmt_kn(m['missed_grant_rate'])}, "
            f"human-read {_fmt_kn(m['human_read_share'])}"
        )
    print(f"wrote {out_path}")
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
