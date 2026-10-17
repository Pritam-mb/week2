"""Stage 1: extract structured eligibility conditions from one opportunity.

For a single opportunity this reads the free-text eligibility text and
synopsis and returns a list of :class:`~src.models.Condition` objects, each
carrying a verbatim quote copied from the source. Results are cached on disk
by a prefix of the normalised-text hash, so the model is only called once per
distinct text.

Backends share one protocol: ``extract(prompt: str) -> str`` returning the raw
assistant text (expected to be JSON). ``MockBackend`` is a deterministic,
offline backend whose quotes are guaranteed to be verbatim substrings because
they are sliced out of the source text it is handed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from typing import Any, Protocol

import requests

from .config import get, load_config
from .io_utils import load_opportunities, opportunity_from_raw, read_json, write_json
from .models import Condition, ConditionType, Opportunity, Polarity
from .verify import is_verbatim_quote  # noqa: F401  (re-exported for callers)

# Markers let the offline mock recover the exact source text from the prompt
# without any mutable backend state.
SOURCE_BEGIN = "<<<SOURCE>>>"
SOURCE_END = "<<<END_SOURCE>>>"


def _provider_api_key() -> str | None:
    """Return the configured provider key, preferring the generic alias."""
    return os.environ.get("GFP_API_KEY") or os.environ.get("TINKER_API_KEY")

EXTRACTION_SYSTEM = (
    "You are a meticulous grant-eligibility analyst. You extract only what the "
    "source text states. You never infer, paraphrase or invent a quote."
)

EXTRACTION_PROMPT = f"""\
Extract the applicant eligibility conditions from the grant opportunity below.

Rules:
- Output ONLY a JSON object of exactly this form:
  {{"conditions":[{{"type":"<one of org_type|location|citizenship_or_residency|size|prior_award_or_status|partnership_required|cost_share|other>","polarity":"<required|excluded>","value":"<short phrase>","quote":"<verbatim sentence copied exactly from the text>"}}]}}
- ``quote`` MUST be a verbatim sentence copied character-for-character from the source text. Never invent, complete or reword a quote.
- Use ``polarity`` "required" when the sentence states who may apply, and "excluded" when it states who may not apply.
- Use the ``type`` that best fits the condition; use "other" when none fits.
- If the source states no eligibility condition, return {{"conditions":[]}}.
- Do not add any prose, commentary or markdown fences.

Opportunity: __OPP_ID__ — __TITLE__ (agency: __AGENCY__)

Source text:
{SOURCE_BEGIN}
__SOURCE_TEXT__
{SOURCE_END}
"""


class Backend(Protocol):
    """The one method every extraction backend implements."""

    def extract(self, prompt: str) -> str:  # pragma: no cover - protocol
        ...


# Sentence splitter that keeps the terminal punctuation. The lookahead avoids
# splitting decimals and abbreviations such as "U.S." mid-word.
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)")


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` spans of sentences, punctuation included."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        spans.append((start, match.end()))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


# Ordered mock rules: (regex, condition type, polarity, value phrase).
_MOCK_RULES: list[tuple[str, str, str, str]] = [
    (r"\b501\(c\)\(3\)", "org_type", "required", "501(c)(3) nonprofit"),
    (r"\bnon[- ]?profit\b", "org_type", "required", "nonprofit organization"),
    (r"\bfor[- ]?profit\b|\bcommercial organization\b", "org_type", "required", "for-profit organization"),
    (r"\bsmall business\b", "size", "required", "small business"),
    (r"\b(?:tribal (?:government|organization|organizations|applicant|applicants)|native american (?:tribal )?organization|indian tribe)\b", "org_type", "required", "tribal organization"),
    (r"\b(?:universit(?:y|ies)|college(?:s)?|institution(?:s)? of higher education)\b", "org_type", "required", "institution of higher education"),
    (r"\bstate government\b|\bagency\b", "org_type", "required", "government entity"),
    (r"\bindividual\b|\bsole proprietor\b", "org_type", "required", "individual applicant"),
    (r"\bu\.?s\.?\b|\bunited states\b|\bdomestic\b", "location", "required", "U.S.-based"),
    (r"\blocated in\b|\bbased in\b|\breside in\b|\bresidency\b|\bresiden(?:t|cy)\b|\bcitizen", "location", "required", "specified location"),
    (r"\bcitizenship\b|\bcitizen\b", "citizenship_or_residency", "required", "U.S. citizenship/residency"),
    (r"\bpartnership\b|\bcollaborat\w+\b|\bconsortium\b", "partnership_required", "required", "partnership/collaboration"),
    (r"\bmatching\b|\bcost[- ]?share\b|\bcost sharing\b", "cost_share", "required", "cost share/matching"),
    (r"\bprior\b|\bpreviously (?:funded|awarded)\b|\bcurrent grantee\b", "prior_award_or_status", "required", "prior award/status"),
    (r"\bonly\b[^.!?]*\bmay apply\b", "other", "required", "restricted eligibility"),
    (r"\brestricted to\b", "other", "required", "restricted eligibility"),
    (r"\blimited to\b", "other", "required", "restricted eligibility"),
    (r"\bnot eligible\b|\bineligible\b|\bexcluded\b|\bnot permitted\b", "other", "excluded", "excluded applicant"),
    (r"\bmust\b", "other", "required", "stated requirement"),
    (r"\beligible\b", "other", "required", "eligible applicant"),
]


def _mock_conditions_from_text(source_text: str) -> list[Condition]:
    """Scan ``source_text`` and build conditions whose quotes are its sentences."""
    conditions: list[Condition] = []
    seen: set[tuple[str, str, str]] = set()
    for start, end in _sentence_spans(source_text):
        sentence = source_text[start:end].strip()
        if not sentence:
            continue
        lowered = sentence.lower()
        for pattern, ctype, polarity, value in _MOCK_RULES:
            if not re.search(pattern, lowered):
                continue
            # Avoid treating a program description (for example, "supports
            # tribal languages") as an applicant restriction. The offline
            # backend is a plumbing fallback, but it should still model the
            # quote-or-abstain contract conservatively.
            if ctype in {"org_type", "size"} and not any(
                cue in lowered
                for cue in (
                    "eligible",
                    "eligibility",
                    "applicant",
                    "may apply",
                    "restricted",
                    "limited to",
                    "only",
                    "must",
                    "excluded",
                    "not permitted",
                )
            ):
                continue
            key = (ctype, polarity, sentence)
            if key in seen:
                continue
            seen.add(key)
            conditions.append(
                Condition(
                    type=ConditionType(ctype),
                    polarity=Polarity(polarity),
                    value=value,
                    quote=sentence,
                )
            )
    return conditions


def _extract_marked_source(prompt: str) -> str:
    """Pull the source text out of the prompt markers."""
    if SOURCE_BEGIN in prompt and SOURCE_END in prompt:
        inner = prompt.split(SOURCE_BEGIN, 1)[1].split(SOURCE_END, 1)[0]
        return inner.strip("\n")
    return ""


class MockBackend:
    """Deterministic offline backend.

    Guarantee: every quote is a slice of the source text (a whole sentence
    taken verbatim), so :func:`src.verify.is_verbatim_quote` always passes.
    """

    def __init__(self, source_text: str | None = None) -> None:
        self.source_text = source_text

    def extract(self, prompt: str) -> str:
        source = self.source_text
        if source is None:
            source = _extract_marked_source(prompt)
        conditions = _mock_conditions_from_text(source)
        return json.dumps(
            {"conditions": [c.to_dict() for c in conditions]},
            ensure_ascii=False,
        )


class OpenAICompatibleBackend:
    """POST to an OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(
        self,
        base_model: str,
        provider_base_url: str | None,
        api_key: str | None,
        timeout: float = 120.0,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        provider: str = "openai-compatible",
        reasoning_effort: Any = False,
        separate_reasoning: bool = False,
    ) -> None:
        if not base_model:
            raise ValueError("OpenAICompatibleBackend requires a base_model name")
        if not provider_base_url:
            raise ValueError(
                "No provider base URL configured. Set extract.provider_base_url "
                "or the GFP_PROVIDER_BASE_URL environment variable."
            )
        if not api_key:
            raise ValueError(
                "No API key configured. Set the GFP_API_KEY environment variable."
            )
        self.base_model = base_model
        self.provider_base_url = provider_base_url
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.provider = provider
        self.reasoning_effort = reasoning_effort
        self.separate_reasoning = separate_reasoning

    def _endpoint(self) -> str:
        base = self.provider_base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def extract(self, prompt: str) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.base_model,
            "messages": [
                {"role": "system", "content": EXTRACTION_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        # Tinker Qwen3.5 otherwise spends a small extraction request on its
        # reasoning trace and may return an empty message.content. Keep this
        # provider-specific behavior out of generic OpenAI-compatible APIs.
        if self.provider.lower() == "tinker":
            payload["reasoning_effort"] = self.reasoning_effort
            payload["separate_reasoning"] = self.separate_reasoning
        response = requests.post(
            self._endpoint(),
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


class FineTunedBackend(OpenAICompatibleBackend):
    """Same protocol as the base backend, pointed at the fine-tuned model."""

    def __init__(self, config: dict[str, Any], **overrides: Any) -> None:
        model = get(config, "extract.fine_tuned_model")
        if not model:
            raise ValueError(
                "FineTunedBackend requested but extract.fine_tuned_model is not set"
            )
        super().__init__(
            base_model=model,
            provider_base_url=get(config, "extract.provider_base_url")
            or os.environ.get("GFP_PROVIDER_BASE_URL"),
            api_key=_provider_api_key(),
            timeout=get(config, "extract.timeout_seconds", default=120.0),
            max_tokens=get(config, "extract.max_output_tokens", default=1024),
            temperature=get(config, "extract.temperature", default=0.0),
            provider=get(config, "extract.provider", default="tinker"),
            reasoning_effort=get(config, "extract.reasoning_effort", default=False),
            separate_reasoning=get(config, "extract.separate_reasoning", default=False),
            **overrides,
        )


def make_backend(config: dict[str, Any], which: str = "prompted") -> Backend:
    """Build a backend. ``which`` is one of prompted, fine_tuned or mock."""
    provider = get(config, "extract.provider", default="mock")
    if which == "mock":
        return MockBackend()
    if which == "fine_tuned":
        return FineTunedBackend(config)
    if which != "prompted":
        raise ValueError(f"Unknown backend {which!r}; expected prompted|fine_tuned|mock")

    return OpenAICompatibleBackend(
        base_model=get(config, "extract.base_model", default=""),
        provider_base_url=get(config, "extract.provider_base_url")
        or os.environ.get("GFP_PROVIDER_BASE_URL"),
        api_key=_provider_api_key(),
        timeout=get(config, "extract.timeout_seconds", default=120.0),
        max_tokens=get(config, "extract.max_output_tokens", default=1024),
        temperature=get(config, "extract.temperature", default=0.0),
        provider=provider,
        reasoning_effort=get(config, "extract.reasoning_effort", default=False),
        separate_reasoning=get(config, "extract.separate_reasoning", default=False),
    )


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def parse_conditions(raw: str) -> list[Condition]:
    """Parse backend text into Conditions, dropping malformed/bad-enum rows."""
    text = _strip_fences(raw)
    try:
        data = json.loads(text)
    except ValueError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except ValueError:
            return []

    if isinstance(data, dict):
        rows = data.get("conditions", [])
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    conditions: list[Condition] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            conditions.append(Condition.from_dict(row))
        except (KeyError, ValueError, TypeError):
            # Bad enum value or missing required key: drop it.
            continue
    return conditions


def _build_prompt(opportunity: Opportunity) -> str:
    return (
        EXTRACTION_PROMPT.replace("__OPP_ID__", opportunity.id or opportunity.opp_number)
        .replace("__TITLE__", opportunity.title)
        .replace("__AGENCY__", opportunity.agency)
        .replace("__SOURCE_TEXT__", opportunity.source_text)
    )


def extract_conditions(
    opportunity: Opportunity, backend: Backend, config: dict[str, Any]
) -> list[Condition]:
    """Extract conditions for one opportunity, caching by backend + text hash.

    The cache holds the model's raw output after schema validation only:
    quotes are NOT filtered here, because quote validity must be measurable
    *before* code enforcement (PRD 8.5). Dropping non-verbatim quotes is the
    verifier's job (src.verify), downstream in the pipeline.

    The cache key includes the backend class name, so a mock run can never
    poison a prompted or fine-tuned cache for the same text.
    """
    cache_dir = get(config, "extract.cache_dir") or os.path.join(
        tempfile.gettempdir(), "grant_fine_print_extract"
    )
    backend_name = type(backend).__name__
    hash_len = int(get(config, "cache.hash_prefix_length", default=12))
    cache_key = opportunity.text_hash[:hash_len]
    cache_path = os.path.join(cache_dir, backend_name, f"{cache_key}.json")

    if os.path.exists(cache_path):
        cached = read_json(cache_path)
        if isinstance(cached, dict):
            return parse_conditions(json.dumps(cached.get("conditions", cached)))

    prompt = _build_prompt(opportunity)
    raw = backend.extract(prompt)
    candidates = parse_conditions(raw)

    write_json(
        cache_path,
        {
            "hash": opportunity.text_hash,
            "cache_key": cache_key,
            "backend": backend_name,
            "opportunity_id": opportunity.id,
            "conditions": [c.to_dict() for c in candidates],
        },
    )
    return candidates


def _write_result(out_dir: str, opportunity: Opportunity, conditions: list[Condition]) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{opportunity.id}.json")
    write_json(
        path,
        {
            "opportunity_id": opportunity.id,
            "conditions": [c.to_dict() for c in conditions],
        },
    )
    return path


def _load_opportunity_file(path: str) -> Opportunity:
    data = read_json(path)
    if data is None:
        raise ValueError(f"Could not read opportunity JSON from {path}")
    if isinstance(data, list):
        if not data:
            raise ValueError(f"No opportunities found in {path}")
        data = data[0]
    # CLI inputs are usually cached Grants.gov payloads (camelCase and nested
    # synopsis), not already-normalized Opportunity dictionaries.
    if isinstance(data, dict) and (
        "opp_number" not in data and "eligibility_text" not in data
    ):
        return opportunity_from_raw(data)
    return Opportunity.from_dict(data)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 1: extract eligibility conditions")
    parser.add_argument("--opportunity", help="Path to a single cached opportunity JSON")
    parser.add_argument("--all", action="store_true", help="Process every opportunity in the raw dir")
    parser.add_argument(
        "--backend",
        default="prompted",
        choices=["prompted", "fine_tuned", "mock"],
        help="Which backend to use",
    )
    parser.add_argument(
        "--out",
        default="results/extract_cache",
        help="Directory for per-opportunity extraction results",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config = load_config()
    backend = make_backend(config, which=args.backend)

    if args.all:
        raw_dir = get(config, "cache.raw_dir", default="data/raw")
        opportunities = load_opportunities(raw_dir)
    elif args.opportunity:
        opportunities = [_load_opportunity_file(args.opportunity)]
    else:
        raise SystemExit("Provide --opportunity PATH or --all")

    for opportunity in opportunities:
        conditions = extract_conditions(opportunity, backend, config)
        _write_result(args.out, opportunity, conditions)
        print(f"{opportunity.id}: {len(conditions)} conditions -> {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
