"""A failed GitHub lookup must never authorize replacing a release."""
from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock
import urllib.error

import pytest


@pytest.fixture
def publisher(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("publish_plan72_release")


def test_only_real_404_means_absent(publisher, monkeypatch):
    def missing(request, timeout):
        assert request.full_url.endswith("/git/ref/tags/v0.3.0-alpha.5.1")
        assert request.get_header("Authorization") == "Bearer test-token"
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
    monkeypatch.setattr(publisher.urllib.request, "urlopen", missing)
    publisher.require_absent("bliek79/doems", "git/ref/tags/v0.3.0-alpha.5.1", "test-token")


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_auth_rate_limit_and_server_failures_block_publication(publisher, monkeypatch, status):
    def fail(request, timeout):
        raise urllib.error.HTTPError(request.full_url, status, "Failure", {}, None)
    monkeypatch.setattr(publisher.urllib.request, "urlopen", fail)
    with pytest.raises(RuntimeError, match="publication blocked"):
        publisher.require_absent("bliek79/doems", "releases/tags/v0.3.0-alpha.5.1", "test-token")


def test_existing_release_cannot_be_replaced(publisher, monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.status = 200
    monkeypatch.setattr(publisher.urllib.request, "urlopen", lambda request, timeout: response)
    with pytest.raises(RuntimeError, match="Refusing to replace"):
        publisher.require_absent("bliek79/doems", "releases/tags/v0.3.0-alpha.5.1", "test-token")


def test_network_failure_is_not_absence(publisher, monkeypatch):
    def fail(request, timeout):
        raise urllib.error.URLError("connection failed")
    monkeypatch.setattr(publisher.urllib.request, "urlopen", fail)
    with pytest.raises(urllib.error.URLError):
        publisher.require_absent("bliek79/doems", "releases/tags/v0.3.0-alpha.5.1", "test-token")
