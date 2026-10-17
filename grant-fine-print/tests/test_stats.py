"""Unit tests for Wilson score confidence intervals and table macro rendering."""

from __future__ import annotations

import pytest
from flask import render_template_string

from app.main import create_app
from src.config import load_config
from src.stats import compute_share_cell, format_wilson_ci, wilson_ci


def test_wilson_ci_permissive_sample():
    # 16 of 26 permissive grants had hard disqualifiers in free text
    low, high = wilson_ci(16, 26, 0.95)
    # Expected ~42.5% to ~77.6%
    assert 0.42 <= low <= 0.43
    assert 0.77 <= high <= 0.78


def test_format_wilson_ci_renders_k_of_n_and_ci():
    formatted = format_wilson_ci(16, 26, 0.95)
    assert "16 of 26" in formatted
    assert "61.5%" in formatted
    assert "95% CI" in formatted
    assert "42.5%" in formatted
    assert "77.6%" in formatted


def test_compute_share_cell_small_sample():
    cell_small = compute_share_cell(16, 26, small_sample_threshold=30)
    assert cell_small["is_small_sample"] is True
    assert cell_small["k_of_n"] == "16 of 26"
    assert "95% CI" in cell_small["ci_text"]

    cell_large = compute_share_cell(180, 528, small_sample_threshold=30)
    assert cell_large["is_small_sample"] is False
    assert cell_large["k_of_n"] == "180 of 528"
    assert cell_large["ci_text"] == ""


def test_wilson_ci_boundary_values():
    low_0, high_0 = wilson_ci(0, 10, 0.95)
    assert low_0 == 0.0
    assert 0.0 < high_0 < 0.35

    low_full, high_full = wilson_ci(10, 10, 0.95)
    assert 0.65 < low_full < 1.0
    assert high_full == 1.0

    assert wilson_ci(0, 0) == (0.0, 0.0)
    assert format_wilson_ci(0, 0) == "0 of 0 (0.0%)"


def test_study_table_macro_renders_k_of_n_and_ci_string():
    """Verify that the Jinja table macro renders 'k of N' and Wilson CI from sample data."""
    app = create_app(load_config())
    with app.test_request_context():
        study_sample = {
            "total": 528,
            "a_count": 180,
            "c_count": 221,
            "b": {
                "permissive_total": 26,
                "permissive_with_disqualifier": 16,
                "others_total": 15,
                "others_with_disqualifier": 12,
            },
        }
        tpl = """
        {% import "macros/table.html" as dt %}
        {{ dt.render_study_table(study, threshold=30) }}
        """
        html = render_template_string(tpl, study=study_sample)

        # Asserts required by user spec
        assert "16 of 26" in html
        assert "61.5%" in html
        assert "small sample" in html
        assert "95% CI" in html
        assert "180 of 528" in html
        assert "34.1%" in html
        assert "table-wrap" in html
        assert "<table class=\"dt\"" in html
