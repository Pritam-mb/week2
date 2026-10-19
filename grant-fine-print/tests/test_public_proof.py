"""Public proof requests serve only prebuilt, explicitly allowlisted files."""

from __future__ import annotations

import builtins
import io
import os
from pathlib import Path

import pytest

import app.main as main_module
import src.config as config_module
import src.extract as extract_module
import src.pipeline as pipeline_module


PUBLIC_FILES = [
    ("/proof/", "reports/proof_pack/index.html", "text/html"),
    ("/proof/PROOF.md", "reports/proof_pack/PROOF.md", "text/plain"),
    ("/proof/examples.json", "reports/proof_pack/examples.json", "application/json"),
    ("/proof/provenance.json", "reports/proof_pack/provenance.json", "application/json"),
    ("/proof/hero.png", "docs/images/btod-hero.png", "image/png"),
    ("/proof/hero.svg", "docs/images/btod-hero.svg", "image/svg+xml"),
]


@pytest.fixture(autouse=True)
def forbid_proof_side_effects(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Proof requests must not run models, load config, or render templates")

    for module, names in (
        (main_module, ("run_pipeline", "load_config", "render_template", "_cfg",
                       "load_manifest", "load_opportunities", "load_profiles", "pull_grants")),
        (pipeline_module, ("run", "run_model_system", "make_backend", "extract_conditions")),
        (extract_module, ("make_backend", "extract_conditions", "_provider_api_key")),
        (config_module, ("load_config", "load_dotenv")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, fail)
    for backend in (extract_module.MockBackend, extract_module.OpenAICompatibleBackend,
                    extract_module.FineTunedBackend):
        monkeypatch.setattr(backend, "__init__", fail)
        monkeypatch.setattr(backend, "extract", fail)

    # Guard both normal open() and pathlib/io access without reading any .env.
    def guarded(original):
        def open_without_env(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                name = Path(os.fsdecode(file)).name.lower()
                if name == ".env" or name.startswith(".env."):
                    pytest.fail("Public proof must not read .env files")
            return original(file, *args, **kwargs)
        return open_without_env

    monkeypatch.setattr(builtins, "open", guarded(builtins.open))
    monkeypatch.setattr(io, "open", guarded(io.open))
    monkeypatch.setattr(os, "open", guarded(os.open))


@pytest.fixture()
def proof_root(tmp_path, monkeypatch):
    contents = {
        "reports/proof_pack/index.html": (
            b'<!doctype html><html><body>&lt;script&gt;alert(&quot;x&quot;)'
            b'&lt;/script&gt; {{ 7 * 7 }}</body></html>\n'
        ),
        "reports/proof_pack/PROOF.md": b"# Saved public evidence\n",
        "reports/proof_pack/examples.json": b'{"examples": []}\n',
        "reports/proof_pack/provenance.json": b'{"source": "saved"}\n',
        "docs/images/btod-hero.png": b"\x89PNG\r\n\x1a\npublic hero",
        "docs/images/btod-hero.svg": b'<svg xmlns="http://www.w3.org/2000/svg"/>',
        # Existing non-allowlisted files must still be inaccessible.
        "reports/proof_pack/private.txt": b"private proof file",
        "reports/proof_pack/hero.png": b"wrong proof-pack hero",
        "docs/images/private.png": b"private image",
        "config.yaml": b"private configuration",
        "app/main.py": b"private source",
        "results/private.json": b'{"private": true}',
    }
    for relative_path, data in contents.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    monkeypatch.setattr(main_module, "_ROOT", tmp_path)
    return tmp_path


@pytest.fixture(params=[{}, {"storage": {"backend": "postgres"},
                          "extract": {"provider": "unconfigured"}}],
                ids=["minimal-config", "unavailable-provider-and-storage"])
def client(request, proof_root):
    app = main_module.create_app(request.param)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("url,relative_path,mimetype", PUBLIC_FILES)
def test_public_files_are_served_verbatim(client, proof_root, method, url, relative_path, mimetype):
    expected = (proof_root / relative_path).read_bytes()
    with client.open(url, method=method) as response:
        assert response.status_code == 200
        assert response.mimetype == mimetype
        assert response.content_length == len(expected)
        assert response.data == (expected if method == "GET" else b"")
        assert "Set-Cookie" not in response.headers


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_proof_redirects_to_canonical_slash(client, method):
    with client.open("/proof", method=method) as response:
        assert response.status_code == 308
        assert response.headers["Location"].endswith("/proof/")
    with client.open("/proof", method=method, follow_redirects=True) as response:
        assert response.status_code == 200
        assert response.mimetype == "text/html"


def test_preescaped_html_is_not_rendered_or_modified(client):
    with client.get("/proof/?q=%3Cscript%3Eunsafe%3C/script%3E") as response:
        body = response.get_data(as_text=True)
        assert "&lt;script&gt;" in body
        assert "<script>" not in body
        assert "{{ 7 * 7 }}" in body
        assert "unsafe" not in body


@pytest.mark.parametrize("path", [
    ".env", ".env.example", "config.yaml", "private.txt", "index.html",
    "app/main.py", "results/private.json", "docs/images/private.png",
    "docs/images/btod-hero.png", "btod-hero.png", "reports/proof_pack/PROOF.md",
    "hero.png/private", "hero.png/", "PROOF.md/", "proof.md",
    "../config.yaml", "../../.env", "%2e%2e/config.yaml",
    "%2e%2e/%2e%2e/.env", "..%2f..%2f.env", "..%5c..%5c.env",
    "%252e%252e%252f.env", "C:%5cWindows%5cwin.ini", "%00",
    "reports/", "docs/", ".git/config",
])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_unlisted_files_and_traversal_are_404(client, path, method):
    with client.open(f"/proof/{path}", method=method) as response:
        assert response.status_code == 404
        assert response.mimetype == "text/plain"
        assert response.data == (b"Not found.\n" if method == "GET" else b"")


@pytest.mark.parametrize("url", ["/proof", *[row[0] for row in PUBLIC_FILES], "/proof/.env"])
def test_post_is_not_allowed(client, url):
    with client.post(url) as response:
        assert response.status_code == 405


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("url,relative_path,mimetype", PUBLIC_FILES)
def test_missing_artifact_is_404(client, proof_root, method, url, relative_path, mimetype):
    (proof_root / relative_path).unlink()
    with client.open(url, method=method) as response:
        assert response.status_code == 404
        assert response.mimetype == "text/plain"


def test_missing_artifact_directory_is_404(client, proof_root):
    pack = proof_root / "reports" / "proof_pack"
    for path in pack.iterdir():
        path.unlink()
    pack.rmdir()
    with client.get("/proof/") as response:
        assert response.status_code == 404


def test_directory_in_place_of_artifact_is_404(client, proof_root):
    artifact = proof_root / "reports" / "proof_pack" / "examples.json"
    artifact.unlink()
    artifact.mkdir()
    with client.get("/proof/examples.json") as response:
        assert response.status_code == 404
