"""Unit tests for src/http_client.py (network fully mocked)."""

from __future__ import annotations

import requests

from src import http_client as http_module
from src.config import CONFIG
from src.http_client import HttpClient


class FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)


def test_get_text_retries_on_timeout_then_succeeds(monkeypatch):
    monkeypatch.setattr(http_module.time, "sleep", lambda _: None)
    client = HttpClient()
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        assert "User-Agent" in headers
        assert timeout is not None
        if calls["n"] < 3:
            raise requests.exceptions.Timeout()
        return FakeResponse(text="payload")

    monkeypatch.setattr(client.session, "get", fake_get)
    assert client.get_text("https://example.com/") == "payload"
    assert calls["n"] == 3


def test_get_text_fails_fast_on_4xx(monkeypatch):
    monkeypatch.setattr(http_module.time, "sleep", lambda _: None)
    client = HttpClient()
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        return FakeResponse(status_code=404)

    monkeypatch.setattr(client.session, "get", fake_get)
    assert client.get_text("https://example.com/missing") is None
    assert calls["n"] == 1  # 4xx must not be retried


def test_get_text_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(http_module.time, "sleep", lambda _: None)
    client = HttpClient()
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(client.session, "get", fake_get)
    assert client.get_text("https://example.com/") is None
    assert calls["n"] == CONFIG.max_retries


def test_get_json_parses_and_rejects_invalid(monkeypatch):
    client = HttpClient()
    monkeypatch.setattr(client, "get_text", lambda url: '{"hits": []}')
    assert client.get_json("https://example.com/api") == {"hits": []}

    monkeypatch.setattr(client, "get_text", lambda url: "not json")
    assert client.get_json("https://example.com/api") is None

    monkeypatch.setattr(client, "get_text", lambda url: None)
    assert client.get_json("https://example.com/api") is None
