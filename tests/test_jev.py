from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import contract_eval.jev as jev
from contract_eval.jev import (
    JevEvaluator,
    JevResponseError,
    JevTransportError,
    OfflineCacheMiss,
    TransportResponse,
    build_request,
    cache_key_for_request,
    evaluator_spec_sha256,
    extract_scores,
    validate_frozen_config,
)

STATE = {"case_id": "case-1", "prefix": [{"sequence": 1, "kind": "tool"}]}
CONSTRAINTS = [{"id": "no_tests", "text": "Do not modify tests."}]


def valid_body(probability: float = 0.8) -> dict[str, object]:
    return {
        "model": "jev-1.13.0",
        "answers": {"no_tests": {"type": "noul", "noul": probability}},
        "usage": {"input_tokens": 31, "output_tokens": 5},
    }


class FakeTransport:
    def __init__(self, body: dict[str, object] | None = None, status: int = 200) -> None:
        self.body = body or valid_body()
        self.status = status
        self.calls = 0
        self.payloads: list[dict[str, object]] = []

    def post_json(self, url, headers, payload, timeout_seconds):
        self.calls += 1
        self.payloads.append(dict(payload))
        return TransportResponse(status=self.status, body=self.body)


def online_evaluator(tmp_path: Path, transport: FakeTransport) -> JevEvaluator:
    return JevEvaluator(
        tmp_path / "private-cache", transport=transport, allow_network=True, api_key="test-key"
    )


def test_build_request_batches_atomic_questions_and_copies_state() -> None:
    state = {"prefix": [{"sequence": 1}]}
    request = build_request(
        state,
        [
            {"id": "no_tests", "text": "Do not modify tests."},
            {"id": "src_only", "text": "Only modify src/."},
        ],
    )
    state["prefix"][0]["sequence"] = 999

    assert request["model"] == "jev-1.13.0"
    assert set(request["questions"]) == {"no_tests", "src_only"}
    assert request["state"]["prefix"][0]["sequence"] == 1
    assert request["questions"]["no_tests"]["type"] == "noul"


def test_cache_key_and_score_extraction_share_the_exact_batched_request() -> None:
    request = build_request(STATE, CONSTRAINTS)
    assert cache_key_for_request(STATE, CONSTRAINTS) == jev.sha256_json(
        {"evaluator_spec_sha256": evaluator_spec_sha256(), "request": request}
    )
    assert extract_scores(valid_body(0.35), request) == {"no_tests": 0.35}


def test_frozen_monitor_config_matches_executable_spec() -> None:
    config_path = (
        Path(__file__).parents[1] / "configs" / "evaluators" / "jev-contract-monitor-v1.json"
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert config["adapter_evaluator_id"] == jev.EVALUATOR_ID
    assert config["evaluator_spec_sha256"] == evaluator_spec_sha256()
    assert config["model"] == jev.MODEL_ID
    assert validate_frozen_config(config) == config
    config["representations"] = ["normalized_raw_v2"]
    with pytest.raises(jev.FrozenConfigError):
        validate_frozen_config(config)


def test_cache_hit_is_offline_and_request_mutations_change_identity(
    tmp_path: Path, monkeypatch
) -> None:
    transport = FakeTransport()
    evaluator = online_evaluator(tmp_path, transport)
    first = evaluator.evaluate(STATE, CONSTRAINTS)

    offline = JevEvaluator(tmp_path / "private-cache")
    hit = offline.evaluate(STATE, CONSTRAINTS)
    assert hit.from_cache is True
    assert hit.cache_key == first.cache_key
    assert transport.calls == 1

    with pytest.raises(OfflineCacheMiss):
        offline.evaluate({**STATE, "case_id": "case-2"}, CONSTRAINTS)
    with pytest.raises(OfflineCacheMiss):
        offline.evaluate(STATE, [{"id": "no_tests", "text": "Tests are protected."}])
    monkeypatch.setattr(jev, "MODEL_ID", "jev-1.13.1")
    with pytest.raises(OfflineCacheMiss):
        offline.evaluate(STATE, CONSTRAINTS)


def test_force_keeps_prior_cache_record_append_only(tmp_path: Path) -> None:
    transport = FakeTransport()
    evaluator = online_evaluator(tmp_path, transport)
    first = evaluator.evaluate(STATE, CONSTRAINTS)
    forced = evaluator.evaluate(STATE, CONSTRAINTS, force=True)

    assert first.cache_key == forced.cache_key
    assert first.call_id == first.cache_key
    assert forced.call_id != forced.cache_key
    assert first.cache_path != forced.cache_path
    assert first.cache_path.is_file() and forced.cache_path.is_file()
    assert transport.calls == 2


def test_private_cache_records_exact_request_and_executable_spec_hash(tmp_path: Path) -> None:
    transport = FakeTransport()
    result = online_evaluator(tmp_path, transport).evaluate(STATE, CONSTRAINTS)
    entry = json.loads(result.cache_path.read_text(encoding="utf-8"))

    assert entry["request"] == result.request
    assert entry["request_sha256"] == jev.sha256_json(result.request)
    assert entry["metadata"]["evaluator_spec_sha256"] == evaluator_spec_sha256()

    entry["request"]["state"]["case_id"] = "tampered"
    result.cache_path.write_text(json.dumps(entry), encoding="utf-8")
    with pytest.raises(JevResponseError):
        JevEvaluator(tmp_path / "private-cache").evaluate(STATE, CONSTRAINTS)


@pytest.mark.parametrize(
    "body",
    [
        {"model": "jev-1.13.0", "answers": {}, "usage": {"input_tokens": 1, "output_tokens": 1}},
        {
            "model": "jev-1.13.0",
            "answers": {"no_tests": {"type": "choice"}},
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
        {
            "model": "jev-1.13.0",
            "answers": {"no_tests": {"type": "noul", "noul": 1.2}},
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
        {"model": "jev-1.13.0", "answers": {"no_tests": {"type": "noul", "noul": 0.2}}},
        {
            "model": "jev-preview",
            "answers": {"no_tests": {"type": "noul", "noul": 0.2}},
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    ],
)
def test_invalid_or_missing_answers_are_rejected(tmp_path: Path, body: dict[str, object]) -> None:
    with pytest.raises(JevResponseError):
        online_evaluator(tmp_path, FakeTransport(body)).evaluate(STATE, CONSTRAINTS)


def test_transport_errors_are_sanitized(tmp_path: Path) -> None:
    class LeakyTransport:
        def post_json(self, *args, **kwargs):
            raise RuntimeError("Bearer super-secret-provider-message")

    with pytest.raises(JevTransportError) as error:
        JevEvaluator(
            tmp_path / "private-cache",
            transport=LeakyTransport(),
            allow_network=True,
            api_key="test-key",
        ).evaluate(STATE, CONSTRAINTS)
    assert "super-secret" not in str(error.value)


def test_transport_rejects_oversized_request_before_network(monkeypatch) -> None:
    class UnexpectedUrlopen:
        def __call__(self, *args, **kwargs):
            raise AssertionError("network should not be reached")

    monkeypatch.setattr(jev, "urlopen", UnexpectedUrlopen())
    transport = jev.UrllibTransport()
    with pytest.raises(JevTransportError, match="local size limit"):
        transport.post_json(
            "https://example.invalid",
            {},
            {"payload": "x" * jev.MAX_REQUEST_BYTES},
            timeout_seconds=1,
        )


def test_cached_response_is_validated(tmp_path: Path) -> None:
    cache_dir = tmp_path / "private-cache"
    transport = FakeTransport()
    first = online_evaluator(tmp_path, transport).evaluate(STATE, CONSTRAINTS)
    cached = json.loads(first.cache_path.read_text(encoding="utf-8"))
    cached["response"]["answers"] = {}
    first.cache_path.write_text(json.dumps(cached), encoding="utf-8")

    with pytest.raises(JevResponseError):
        JevEvaluator(cache_dir).evaluate(STATE, CONSTRAINTS)


def test_cache_read_is_bounded_even_if_the_file_changes_after_cache_lookup(tmp_path: Path) -> None:
    transport = FakeTransport()
    first = online_evaluator(tmp_path, transport).evaluate(STATE, CONSTRAINTS)
    first.cache_path.write_bytes(b"{" + (b" " * jev.MAX_CACHE_BYTES))
    with pytest.raises(JevResponseError):
        JevEvaluator(tmp_path / "private-cache").evaluate(STATE, CONSTRAINTS)


def test_cache_metadata_tampering_is_rejected(tmp_path: Path) -> None:
    transport = FakeTransport()
    first = online_evaluator(tmp_path, transport).evaluate(STATE, CONSTRAINTS)
    cached = json.loads(first.cache_path.read_text(encoding="utf-8"))
    cached["metadata"]["latency_seconds"] = 999.0
    first.cache_path.write_text(json.dumps(cached), encoding="utf-8")

    with pytest.raises(JevResponseError):
        JevEvaluator(tmp_path / "private-cache").evaluate(STATE, CONSTRAINTS)


def test_force_requires_network_even_when_cache_exists(tmp_path: Path) -> None:
    transport = FakeTransport()
    evaluator = online_evaluator(tmp_path, transport)
    evaluator.evaluate(STATE, CONSTRAINTS)

    with pytest.raises(OfflineCacheMiss):
        JevEvaluator(tmp_path / "private-cache").evaluate(STATE, CONSTRAINTS, force=True)


def test_concurrent_writers_leave_a_valid_cache_record(tmp_path: Path) -> None:
    transport = FakeTransport()
    evaluator = online_evaluator(tmp_path, transport)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: evaluator.evaluate(STATE, CONSTRAINTS), range(4)))

    assert all(result.response == results[0].response for result in results)
    offline = JevEvaluator(tmp_path / "private-cache").evaluate(STATE, CONSTRAINTS)
    assert offline.from_cache is True
