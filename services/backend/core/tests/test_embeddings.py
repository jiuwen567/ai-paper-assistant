import json
from unittest.mock import patch
from urllib.error import URLError

import pytest
from django.test import override_settings

from core.embeddings import MAX_RESPONSE_BYTES, configuration, encode
from core.parsing import ParseFailure
from core.tests.embedding_provider import provider, response_for


def test_http_batch_order_auth_and_optional_dimensions():
    def respond(payload):
        result = response_for(payload)
        result["data"].reverse()
        return 200, result, {}

    with provider(respond) as requests:
        config = configuration()
        vectors = encode(["温度", "光照"], config)
        assert vectors[0][:2] == [1, 0] and vectors[1][:2] == [0, 1]
        assert requests[0]["path"] == "/v1/embeddings"
        assert requests[0]["authorization"] == "Bearer synthetic-embedding-key"
        assert requests[0]["payload"]["dimensions"] == 512
        assert "synthetic-embedding-key" not in json.dumps(config)
        assert "127.0.0.1" not in json.dumps(config)
        with override_settings(EMBEDDING_SEND_DIMENSIONS=False):
            encode(["温度"], configuration(), query=True)
            assert "dimensions" not in requests[-1]["payload"]


@pytest.mark.parametrize(
    "change",
    [
        {"EMBEDDING_MODEL": "another-model"},
        {"EMBEDDING_BASE_URL": "https://example.com/v1"},
        {"EMBEDDING_DIMENSION": 384},
        {"EMBEDDING_MODEL_REVISION": "v2"},
        {"EMBEDDING_SEND_DIMENSIONS": False},
    ],
)
def test_changed_space_refuses_old_config_before_request(change):
    with provider() as requests:
        config = configuration()
        with override_settings(**change), pytest.raises(ParseFailure, match="embedding_changed"):
            encode(["自制文本"], config)
        assert not requests
        with override_settings(EMBEDDING_API_KEY="rotated-synthetic-key"):
            assert configuration() == config


@pytest.mark.parametrize(
    "change",
    [
        {"EMBEDDING_MODEL": ""},
        {"EMBEDDING_API_KEY": ""},
        {"EMBEDDING_MODEL": "x" * 129},
        {"EMBEDDING_DIMENSION": 0},
        {"EMBEDDING_DIMENSION": 16001},
        {"EMBEDDING_BASE_URL": "https://user:secret@example.com/v1"},
        {"EMBEDDING_BASE_URL": "https://example.com/v1?key=secret"},
        {"EMBEDDING_BASE_URL": "https://example.com/v1#fragment"},
        {"EMBEDDING_BASE_URL": "file:///model"},
        {"DEBUG": False},
    ],
)
def test_invalid_configuration_does_not_request(change):
    with provider() as requests, override_settings(**change):
        with pytest.raises(ParseFailure, match="embedding_unconfigured"):
            configuration()
        assert not requests


@pytest.mark.parametrize(
    "status,retryable", [(401, False), (403, False), (400, False), (429, True), (503, True)]
)
def test_http_failure_is_diagnostic_and_redacted(status, retryable):
    with provider(lambda _: (status, {"error": "private text and secret"}, {})):
        with pytest.raises(ParseFailure) as caught:
            encode(["自制文本"], configuration())
        assert caught.value.code == f"embedding_http_{status}"
        assert caught.value.retryable is retryable
        assert "private" not in caught.value.message


def test_redirect_is_not_followed():
    with provider(lambda _: (307, {}, {"Location": "http://127.0.0.1:1/leak"})) as requests:
        with pytest.raises(ParseFailure, match="embedding_http_307"):
            encode(["自制文本"], configuration())
        assert len(requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"data": []},
        {"data": [{"index": 0, "embedding": [1]}]},
        {"data": [{"index": True, "embedding": [1, 0]}]},
        {"data": [{"index": 2, "embedding": [1, 0]}]},
        {"data": [{"index": 0, "embedding": [True, 0]}]},
        {"data": [{"index": 0, "embedding": [float("nan"), 0]}]},
        {"data": [{"index": 0, "embedding": [1e100, 0]}]},
        {"data": [{"index": 0, "embedding": [1e-100, 0]}]},
        b"invalid json",
        b"x" * (MAX_RESPONSE_BYTES + 1),
    ],
)
def test_invalid_vectors_are_never_returned(body):
    with provider(lambda _: (200, body, {})), override_settings(EMBEDDING_DIMENSION=2):
        with pytest.raises(ParseFailure, match="embedding_result"):
            encode(["自制文本"], configuration())


def test_duplicate_response_indices_are_rejected():
    with (
        provider(lambda _: (200, {"data": [{"index": 0, "embedding": [1, 0]}] * 2}, {})),
        override_settings(EMBEDDING_DIMENSION=2),
    ):
        with pytest.raises(ParseFailure, match="embedding_result"):
            encode(["第一段", "第二段"], configuration())


def test_transport_failure_is_retryable_without_echoing_exception():
    with provider(), patch("core.embeddings.build_opener") as opener:
        opener.return_value.open.side_effect = URLError("private endpoint and key")
        with pytest.raises(ParseFailure) as caught:
            encode(["自制文本"], configuration())
        assert caught.value.code == "embedding_unavailable" and caught.value.retryable
        assert "private" not in caught.value.message
