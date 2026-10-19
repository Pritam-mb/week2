"""Tests for the Flask web app (app.main)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.config import load_config
from src.corrections import load_corrections

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def app_config(tmp_path):
    config = load_config(str(ROOT / "config.yaml"))
    config["profiles_dir"] = str(tmp_path / "profiles")
    config["corrections_path"] = str(tmp_path / "corrections.json")
    config["card"]["output_dir"] = str(tmp_path / "cards")
    config["extract"]["cache_dir"] = str(tmp_path / "extract_cache")
    config["cache"]["raw_dir"] = str(ROOT / "data" / "mock_raw")
    config["cache"]["manifest"] = str(ROOT / "data" / "mock_raw" / "manifest.json")
    config["storage"]["backend"] = "filesystem"
    return config


@pytest.fixture()
def client(app_config):
    from app.main import create_app

    app = create_app(app_config)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def seeded(app_config):
    profiles_dir = Path(app_config["profiles_dir"])
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        "id": "seed-org",
        "name": "Seed Org",
        "org_type": "nonprofit",
        "us_based": True,
        "state": "KY",
        "size_band": "small",
        "focus_keywords": ["rural"],
        "notes": "seeded for tests",
    }
    (profiles_dir / "seed-org.json").write_text(
        json.dumps(profile), encoding="utf-8"
    )
    return profile


def test_dashboard_lists_profiles(client, seeded):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Seed Org" in body
    assert "seed-org" in body
    assert "11 cached opportunit" in body
    assert "pulled" in body


def test_dashboard_selects_configured_default_backend(client, app_config, seeded):
    body = client.get("/").get_data(as_text=True)
    prompted_option = body.split('<option value="prompted"', 1)[1].split("</option>", 1)[0]
    assert "selected" in prompted_option


def test_dashboard_marks_unconfigured_remote_backends(client, seeded):
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'value="fine_tuned"' in body
    assert "fine_tuned (not configured)" in body
    fine_tuned_option = body.split('<option value="fine_tuned"', 1)[1].split("</option>", 1)[0]
    assert "disabled" in fine_tuned_option


def test_unconfigured_fine_tuned_run_explains_configuration_error(client, seeded):
    response = client.post(
        "/run", data={"profile_id": "seed-org", "backend": "fine_tuned"}
    )
    assert response.status_code == 302
    follow = client.get(response.location)
    body = follow.get_data(as_text=True)
    assert "Real fine_tuned inference is not configured" in body
    assert "GFP_PROVIDER_BASE_URL" in body


def test_evidence_has_empty_states_when_result_files_are_missing(client, monkeypatch, tmp_path):
    import app.main as main_module

    monkeypatch.setattr(main_module, "_ROOT", tmp_path)
    resp = client.get("/evidence")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert body.count("Data Not Generated Yet") == 2
    assert "python -m src.study" in body
    assert "python -m src.eval" in body


def test_evidence_handles_corrupt_result_files(client, monkeypatch, tmp_path):
    import app.main as main_module

    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "study.json").write_text("not json", encoding="utf-8")
    (tmp_path / "results" / "eval.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(main_module, "_ROOT", tmp_path)
    resp = client.get("/evidence")
    assert resp.status_code == 200
    assert "Data Not Generated Yet" in resp.get_data(as_text=True)


def test_evidence_distinguishes_historical_benchmark_from_current_matcher(client):
    response = client.get("/evidence")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Historical results, not a live-model score" in body
    assert "25 unique notices" in body
    assert "101/125" in body
    assert "results/source_semantics/REPLAY.md" in body
    assert "five rejections and 120 CHECKs" in body
    assert "Not a fair model-speed comparison" in body


def test_layout_has_mobile_metadata_favicon_footer_and_menu(client, seeded):
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert '<meta name="viewport"' in body
    assert '<meta name="description"' in body
    assert 'href="/static/favicon.svg"' in body
    assert 'aria-controls="site-nav"' in body
    assert "site-nav" in body
    assert f"&copy; {date.today().year}" in body
    assert "https://www.grants.gov/" in body


def test_optional_contact_details_are_clickable(client, app_config, seeded):
    from app.main import create_app

    app_config["app"]["support_email"] = "help@example.test"
    app_config["app"]["support_phone"] = "+1 (555) 010-1234"
    app = create_app(app_config)
    app.config["TESTING"] = True
    body = app.test_client().get("/").get_data(as_text=True)
    assert 'href="mailto:help@example.test"' in body
    assert 'href="tel:+15550101234"' in body


def test_create_profile_writes_json(client, app_config):
    resp = client.post(
        "/profiles/new",
        data={
            "name": "Test Org",
            "org_type": "nonprofit",
            "us_based": "on",
            "state": "CA",
            "size_band": "small",
            "focus_keywords": "rural, health",
            "notes": "hello",
        },
    )
    assert resp.status_code == 302
    path = Path(app_config["profiles_dir"]) / "test-org.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == "test-org"
    assert data["name"] == "Test Org"
    assert data["us_based"] is True
    assert data["focus_keywords"] == ["rural", "health"]
    assert data["notes"] == "hello"


def test_create_profile_slug_collision_gets_suffix(client, seeded, app_config):
    resp = client.post(
        "/profiles/new",
        data={"name": "Seed Org", "org_type": "nonprofit", "us_based": "on"},
    )
    assert resp.status_code == 302
    path = Path(app_config["profiles_dir"]) / "seed-org-2.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == "seed-org-2"


def test_run_produces_cards_and_summary(client, seeded, app_config):
    resp = client.post("/run", data={"profile_id": "seed-org", "backend": "mock"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "MockBackend" in body
    assert "Offline fallback" in body
    assert (Path(app_config["card"]["output_dir"]) / "seed-org.html").exists()


def test_refresh_offline_sample_updates_cache(client, app_config, tmp_path):
    # Keep the refresh smoke test isolated from the committed offline fixture.
    app_config["cache"]["raw_dir"] = str(tmp_path / "raw")
    app_config["cache"]["manifest"] = str(tmp_path / "raw" / "manifest.json")
    resp = client.post("/refresh", data={"mode": "mock"}, follow_redirects=True)
    assert resp.status_code == 200
    assert "Loaded" in resp.get_data(as_text=True)
    assert list(Path(app_config["cache"]["raw_dir"]).glob("*.json"))


def test_refresh_offline_sample_rebuilds_cards_without_provider(
    client, app_config, seeded, tmp_path
):
    app_config["cache"]["raw_dir"] = str(tmp_path / "raw")
    app_config["cache"]["manifest"] = str(tmp_path / "raw" / "manifest.json")
    resp = client.post("/refresh", data={"mode": "mock"}, follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "card rebuild failed" not in body.lower()


def test_card_filter_is_user_visible(client, seeded):
    resp = client.get("/card/seed-org?q=rural&verdict=CHECK&sort=close&backend=mock")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Showing" in body
    assert 'value="rural"' in body
    assert "Closing date" in body
    assert 'name="backend" value="mock"' in body


def test_card_page_renders(client, seeded):
    resp = client.get("/card/seed-org?backend=mock")
    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    body = resp.get_data(as_text=True)
    assert "Seed Org" in body
    assert "Confirm in the original notice." in body
    assert "Record a correction" in body
    assert "/static/style.css" in body
    assert "/static/app.js" in body
    assert 'aria-controls="site-nav"' in body


def test_run_summary_card_links_keep_selected_backend(client, seeded):
    resp = client.post("/run", data={"profile_id": "seed-org", "backend": "mock"})
    assert resp.status_code == 200
    assert "backend=mock" in resp.get_data(as_text=True)


def test_card_unknown_profile_is_404(client, seeded):
    assert client.get("/card/not-a-real-profile").status_code == 404
    assert client.get("/card/..").status_code == 404


def test_unknown_url_uses_custom_404(client):
    resp = client.get("/does-not-exist")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "That page is not available" in body
    assert "Back to dashboard" in body


def test_correct_writes_correction(client, seeded, app_config):
    resp = client.post(
        "/correct",
        data={
            "profile_id": "seed-org",
            "opportunity_id": "MOCK-001",
            "verdict": "CHECK",
            "note": "look closer",
        },
    )
    assert resp.status_code == 302
    corrections = load_corrections(app_config["corrections_path"])
    assert corrections["seed-org|MOCK-001"]["verdict"] == "CHECK"
    assert corrections["seed-org|MOCK-001"]["note"] == "look closer"


def test_correct_invalid_verdict_is_400(client, seeded):
    resp = client.post(
        "/correct",
        data={"profile_id": "seed-org", "opportunity_id": "MOCK-001", "verdict": "MAYBE"},
    )
    assert resp.status_code == 400
    assert "We could not complete that request" in resp.get_data(as_text=True)


def test_correct_unknown_opportunity_is_400(client, seeded):
    resp = client.post(
        "/correct",
        data={
            "profile_id": "seed-org",
            "opportunity_id": "NOT-IN-CACHE",
            "verdict": "CHECK",
        },
    )
    assert resp.status_code == 400


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_discover_link_unknown_opportunity(client):
    resp = client.post("/discover/nonexistent-opp")
    assert resp.status_code == 404
