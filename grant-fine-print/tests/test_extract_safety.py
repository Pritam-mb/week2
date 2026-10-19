"""Offline regression coverage for extraction failure and cache boundaries."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
import requests

import src.extract as extraction
from src.match import match
from src.models import Opportunity, Profile, Verdict


ROW = {
    "type": "org_type",
    "polarity": "required",
    "value": "nonprofit",
    "quote": "Only nonprofits may apply.",
}
VALID = json.dumps({"conditions": [ROW]})
EMPTY = '{"conditions":[]}'


class SyntheticBackend:
    def __init__(self, raw=VALID, **settings):
        self.raw = raw
        self.calls = 0
        self.__dict__.update(settings)

    def extract(self, prompt):
        self.calls += 1
        return self.raw


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Remote calls and .env reads are forbidden")

    monkeypatch.setattr(requests, "post", forbidden)
    monkeypatch.setattr("src.config.load_dotenv", forbidden)


@pytest.fixture
def opportunity():
    return Opportunity(
        id="synthetic", opp_number="TEST-1", title="Test grant",
        agency="Test agency", eligibility_text=ROW["quote"],
    )


@pytest.fixture
def config(tmp_path):
    return {"extract": {"cache_dir": str(tmp_path)}, "cache": {"hash_prefix_length": 1}}


def test_custom_backend_without_identity_attributes_caches(opportunity, config):
    first = SyntheticBackend()
    expected = extraction.extract_conditions(opportunity, first, config)
    second = SyntheticBackend(raw="must not be used")
    assert extraction.extract_conditions(opportunity, second, config) == expected
    assert first.calls == 1
    assert second.calls == 0


@pytest.mark.parametrize("field,before,after", [
    ("base_model", "model-a", "model-b"),
    ("model", "model-a", "model-b"),
    ("provider", "provider-a", "provider-b"),
    ("provider_base_url", "https://one.test/v1", "https://two.test/v1"),
    ("temperature", 0.0, 0.5),
    ("top_p", 0.9, 0.5),
    ("max_tokens", 1024, 2048),
    ("timeout", 10, 20),
    ("reasoning_effort", False, "low"),
    ("separate_reasoning", False, True),
    ("settings", {"top_p": 0.9}, {"top_p": 0.5}),
])
def test_backend_identity_separates_cache(opportunity, config, field, before, after):
    first = SyntheticBackend(**{field: before})
    second = SyntheticBackend(raw=EMPTY, **{field: after})
    assert extraction.extract_conditions(opportunity, first, config)
    assert extraction.extract_conditions(opportunity, second, config) == []
    assert first.calls == second.calls == 1


@pytest.mark.parametrize("field", ["id", "title", "agency", "eligibility_text"])
def test_fully_built_prompt_separates_cache(opportunity, config, field):
    backend = SyntheticBackend()
    extraction.extract_conditions(opportunity, backend, config)
    changed = replace(opportunity, **{field: getattr(opportunity, field) + " changed"})
    extraction.extract_conditions(changed, backend, config)
    assert backend.calls == 2


@pytest.mark.parametrize("template", ["EXTRACTION_PROMPT", "EXTRACTION_SYSTEM"])
def test_prompt_template_separates_cache(opportunity, config, monkeypatch, template):
    backend = SyntheticBackend()
    extraction.extract_conditions(opportunity, backend, config)
    monkeypatch.setattr(extraction, template, getattr(extraction, template) + "\nNew rule.")
    extraction.extract_conditions(opportunity, backend, config)
    assert backend.calls == 2


@pytest.mark.parametrize("field", ["hash", "fingerprint", "version", "conditions"])
def test_invalid_cache_metadata_or_schema_is_not_trusted(
    opportunity, config, tmp_path, field,
):
    backend = SyntheticBackend()
    extraction.extract_conditions(opportunity, backend, config)
    path, = tmp_path.rglob("*.json")
    cached = json.loads(path.read_text(encoding="utf-8"))
    if field == "hash":
        # Matching the old prefix must not suffice.
        cached[field] = opportunity.text_hash[:12] + "0" * 52
        assert cached[field] != opportunity.text_hash
    elif field == "conditions":
        cached[field] = [ROW, {**ROW, "polarity": "invalid"}]
    else:
        cached[field] = "invalid"
    path.write_text(json.dumps(cached), encoding="utf-8")
    backend.raw = EMPTY
    assert extraction.extract_conditions(opportunity, backend, config) == []
    assert backend.calls == 2


def test_legacy_cache_is_not_reused(opportunity, config, tmp_path):
    legacy = tmp_path / "SyntheticBackend" / f"{opportunity.text_hash[:1]}.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"hash": opportunity.text_hash, "conditions": []}))
    backend = SyntheticBackend()
    assert extraction.extract_conditions(opportunity, backend, config)
    assert backend.calls == 1


def test_duplicate_json_fields_in_cache_force_fresh_extraction(opportunity, config, tmp_path):
    backend = SyntheticBackend()
    extraction.extract_conditions(opportunity, backend, config)
    path, = tmp_path.rglob("*.json")
    content = path.read_text(encoding="utf-8")
    assert '"value": "nonprofit"' in content
    path.write_text(content.replace('"value": "nonprofit"',
                                   '"value": "nonprofit", "value": "for-profit"'),
                    encoding="utf-8")
    backend.raw = EMPTY
    assert extraction.extract_conditions(opportunity, backend, config) == []
    assert backend.calls == 2


@pytest.mark.parametrize("raw", [
    None, "", "  ", [], {}, 123,
    "payload-secret", "null", "[]", "{}", '{"conditions":null}',
    '{"conditions":{}}', '{"conditions":[',
    'prose {"conditions":[]} trailing prose',
    '```json\n{"conditions":[]}',
    '{"conditions":[],"conditions":[]}',
    json.dumps({"conditions": [ROW], "unexpected": True}),
    json.dumps({"conditions": [None]}),
    json.dumps({"conditions": [{"type": "org_type", "polarity": "required"}]}),
    json.dumps({"conditions": [{**ROW, "value": None}]}),
    json.dumps({"conditions": [{**ROW, "quote": " "}]}),
    json.dumps({"conditions": [{**ROW, "value": 5}]}),
    json.dumps({"conditions": [ROW, {**ROW, "type": "invalid-secret"}]}),
    json.dumps({"conditions": [ROW, {**ROW, "polarity": "invalid-secret"}]}),
])
def test_failed_output_raises_and_is_not_cached(opportunity, config, tmp_path, raw):
    backend = SyntheticBackend(raw=raw)
    with pytest.raises(ValueError) as error:
        extraction.extract_conditions(opportunity, backend, config)
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__ or error.value.__context__ is None
    assert list(tmp_path.rglob("*.json")) == []
    backend.raw = VALID
    assert extraction.extract_conditions(opportunity, backend, config)
    assert backend.calls == 2


@pytest.mark.parametrize("raw", [EMPTY, f"```json\n{EMPTY}\n```", f"```\n{EMPTY}\n```"])
def test_valid_empty_is_cached_and_matches_check(opportunity, config, raw):
    backend = SyntheticBackend(raw=raw)
    assert extraction.extract_conditions(opportunity, backend, config) == []
    assert extraction.extract_conditions(opportunity, backend, config) == []
    assert backend.calls == 1
    assert match([], Profile(id="p", name="Test"), opportunity.id).verdict == Verdict.CHECK


def test_valid_fenced_rows_and_tolerant_public_parser(opportunity, config):
    backend = SyntheticBackend(raw=f"```json\n{VALID}\n```")
    assert len(extraction.extract_conditions(opportunity, backend, config)) == 1
    mixed = json.dumps({"conditions": [ROW, {**ROW, "type": "invalid"}]})
    assert len(extraction.parse_conditions(mixed)) == 1
    assert extraction.parse_conditions("malformed") == []


def http_backend(**overrides):
    settings = {
        "base_model": "model-a",
        "provider_base_url": "https://provider.test/v1",
        "api_key": "api-secret",
    }
    settings.update(overrides)
    return extraction.OpenAICompatibleBackend(**settings)


def stub_http(monkeypatch, data):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return data

    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(requests, "post", post)
    return calls


def completion(content=VALID, finish_reason="stop"):
    return {"choices": [{"finish_reason": finish_reason, "message": {"content": content}}]}


@pytest.mark.parametrize("data,reason", [
    (completion(VALID, "length"), "truncated"),
    (completion(EMPTY, "length"), "truncated"),
    (completion(None), "message.content"),
    (completion(""), "message.content"),
    (completion("   "), "message.content"),
    (completion([{"text": "payload-secret"}]), "message.content"),
    ({"choices": []}, "schema"),
    ({"choices": [None]}, "schema"),
    ({"choices": [{"message": {}}]}, "schema"),
    ({"error": "payload-secret"}, "schema"),
    (None, "schema"),
])
def test_http_invalid_or_truncated_response_not_cached(
    opportunity, config, tmp_path, monkeypatch, data, reason,
):
    stub_http(monkeypatch, data)
    backend = http_backend()
    before = vars(backend).copy()
    with pytest.raises(ValueError, match=reason) as error:
        extraction.extract_conditions(opportunity, backend, config)
    assert "secret" not in str(error.value)
    assert vars(backend) == before  # No mutable per-call backend diagnostics.
    assert list(tmp_path.rglob("*.json")) == []


def test_http_request_uses_model_and_settings_and_cache_identity(
    opportunity, config, monkeypatch,
):
    calls = stub_http(monkeypatch, completion())
    backend = http_backend(
        provider="tinker", temperature=0.3, max_tokens=512, timeout=7,
        reasoning_effort="low", separate_reasoning=True,
    )
    extraction.extract_conditions(opportunity, backend, config)
    extraction.extract_conditions(opportunity, backend, config)
    assert len(calls) == 1
    endpoint, request = calls[0]
    assert endpoint == "https://provider.test/v1/chat/completions"
    assert request["timeout"] == 7
    assert request["json"] == {
        "model": "model-a",
        "messages": [
            {"role": "system", "content": extraction.EXTRACTION_SYSTEM},
            {"role": "user", "content": extraction._build_prompt(opportunity)},
        ],
        "temperature": 0.3, "max_tokens": 512,
        "reasoning_effort": "low", "separate_reasoning": True,
    }
    backend.base_model = "model-b"
    extraction.extract_conditions(opportunity, backend, config)
    assert len(calls) == 2
    assert calls[1][1]["json"]["model"] == "model-b"


def test_cache_excludes_secrets_and_credential_rotation_keeps_identity(
    opportunity, config, tmp_path, monkeypatch,
):
    calls = stub_http(monkeypatch, completion())
    backend = http_backend(
        provider_base_url="https://url-user:url-password@provider.test/v1?api_key=query-secret",
    )
    extraction.extract_conditions(opportunity, backend, config)
    backend.api_key = "replacement-secret"
    backend.provider_base_url = (
        "https://new-user:new-password@provider.test/v1?api_key=replacement-query-secret"
    )
    extraction.extract_conditions(opportunity, backend, config)
    assert len(calls) == 1
    path, = tmp_path.rglob("*.json")
    cached_text = path.read_text(encoding="utf-8")
    for forbidden in ("api-secret", "url-user", "url-password", "query-secret", "provider.test", "https://"):
        assert forbidden not in cached_text
        assert forbidden not in str(path)
    cached = json.loads(cached_text)
    assert cached["hash"] == opportunity.text_hash
    assert len(cached["fingerprint"]) == 64
    assert path.stem == cached["fingerprint"]
    assert len(path.stem) == 64


def test_nested_settings_credentials_do_not_change_identity(opportunity, config):
    first = SyntheticBackend(settings={
        "top_p": 0.5, "nested": {"api_key": "first-secret", "password": "first-password"},
    })
    second = SyntheticBackend(raw="must not be called", settings={
        "top_p": 0.5, "nested": {"api_key": "new-secret", "password": "new-password"},
    })
    extraction.extract_conditions(opportunity, first, config)
    assert extraction.extract_conditions(opportunity, second, config)
    assert second.calls == 0


def test_http_error_redacts_credentials_and_payload(opportunity, config, monkeypatch):
    def post(*args, **kwargs):
        raise requests.HTTPError("https://user:password@provider.test api-secret payload-secret")

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(ValueError, match="request failed") as error:
        extraction.extract_conditions(opportunity, http_backend(), config)
    assert str(error.value) == "Extraction backend request failed"
    assert error.value.__suppress_context__


def test_http_malformed_json_is_redacted(opportunity, config, monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("payload-secret")

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: Response())
    with pytest.raises(ValueError, match="malformed JSON") as error:
        extraction.extract_conditions(opportunity, http_backend(), config)
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__


def test_shared_http_backend_keeps_response_diagnostics_local(monkeypatch):
    barrier = Barrier(2)

    class Response:
        def __init__(self, truncated):
            self.truncated = truncated

        def raise_for_status(self):
            pass

        def json(self):
            barrier.wait(timeout=5)
            return completion(EMPTY, "length" if self.truncated else "stop")

    def post(url, **kwargs):
        return Response(kwargs["json"]["messages"][1]["content"] == "truncated")

    monkeypatch.setattr(requests, "post", post)
    backend = http_backend()
    before = vars(backend).copy()
    with ThreadPoolExecutor(max_workers=2) as executor:
        good = executor.submit(backend.extract, "complete")
        truncated = executor.submit(backend.extract, "truncated")
        assert good.result(timeout=10) == EMPTY
        with pytest.raises(ValueError, match="truncated"):
            truncated.result(timeout=10)
    assert vars(backend) == before
