"""
Unit tests for SchwabClient._refresh_access_token + _ensure_authenticated.

Mocking strategy:
    - GCP helpers patched at the schwab_client module level:
        retrieve_google_secret_dict, retrieve_firestore_value, store_firestore_value.
    - httpx.post patched at the schwab_client module level.
    - time.time patched per-test when determinism on expires_at is required.

Helper factory `_build_client_with_mocks()` is a contextmanager — every test
that needs the wired-up client uses it via `with`. No shared conftest.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

import pytest

from shared_core.brokers.schwab_client import (
    SchwabAuthError,
    SchwabClient,
    SchwabCredentials,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

_SCHWAB_REFRESH_RESPONSE = {
    "access_token": "new_access_token_value",
    "refresh_token": "new_refresh_token_value",   # Schwab rotates BOTH
    "expires_in": 1800,
    "token_type": "Bearer",
    "scope": "api",
}


@contextmanager
def _build_client_with_mocks(
    *,
    schwab_response: dict | None = None,
    schwab_status: int = 200,
    refresh_token: str | None = "current_refresh_token",
):
    """Build a SchwabClient with all 4 integration points (3 GCP helpers + httpx)
    mocked.

    Yields:
        (client, mock_secret, mock_firestore_get, mock_firestore_set, mock_httpx_post)
    """
    if schwab_response is None:
        schwab_response = dict(_SCHWAB_REFRESH_RESPONSE)

    with ExitStack() as stack:
        mock_secret = stack.enter_context(patch(
            "shared_core.brokers.schwab_client.retrieve_google_secret_dict",
            return_value={"app-key": "ak", "app-secret": "as"},
        ))
        mock_firestore_get = stack.enter_context(patch(
            "shared_core.brokers.schwab_client.retrieve_firestore_value",
            return_value=refresh_token,
        ))
        mock_firestore_set = stack.enter_context(patch(
            "shared_core.brokers.schwab_client.store_firestore_value",
        ))

        mock_response = MagicMock()
        mock_response.status_code = schwab_status
        mock_response.json.return_value = schwab_response
        mock_response.text = json.dumps(schwab_response)
        mock_httpx_post = stack.enter_context(patch(
            "shared_core.brokers.schwab_client.httpx.post",
            return_value=mock_response,
        ))

        creds = SchwabCredentials(api_key="ak", api_secret="as")
        client = SchwabClient(credentials=creds, paper_trading=True)
        yield client, mock_secret, mock_firestore_get, mock_firestore_set, mock_httpx_post


# ── TestRefreshSuccess ────────────────────────────────────────────────────────

class TestRefreshSuccess:

    def test_returns_none(self):
        with _build_client_with_mocks() as (client, *_):
            assert client._refresh_access_token() is None

    def test_updates_access_token(self):
        with _build_client_with_mocks() as (client, *_):
            client._refresh_access_token()
            assert client.credentials.access_token == "new_access_token_value"

    def test_updates_refresh_token(self):
        with _build_client_with_mocks() as (client, *_):
            client._refresh_access_token()
            assert client.credentials.refresh_token == "new_refresh_token_value"

    def test_updates_token_expires_at(self):
        # time.time patched so expires_at is fully deterministic.
        with patch("shared_core.brokers.schwab_client.time.time", return_value=1_000_000.0):
            with _build_client_with_mocks() as (client, *_):
                client._refresh_access_token()
                # 1_000_000 + 1800 (expires_in)
                assert client.credentials.token_expires_at == 1_001_800.0

    def test_persists_full_dict_to_firestore(self):
        with _build_client_with_mocks() as (client, _, _, mock_set, _):
            client._refresh_access_token()
            mock_set.assert_called_once_with(
                project_id="eolo-schwab-agent",
                collection_id="schwab-tokens",
                document_id="schwab-tokens-auth",
                value=_SCHWAB_REFRESH_RESPONSE,
            )

    def test_reads_app_creds_from_secret_manager(self):
        with _build_client_with_mocks() as (client, mock_secret, *_):
            client._refresh_access_token()
            mock_secret.assert_called_once_with(
                gcp_id="eolo-schwab-agent",
                secret_id="cs-app-key",
            )

    def test_reads_refresh_token_from_firestore(self):
        with _build_client_with_mocks() as (client, _, mock_get, _, _):
            client._refresh_access_token()
            mock_get.assert_called_once_with(
                collection_id="schwab-tokens",
                document_id="schwab-tokens-auth",
                key="refresh_token",
                project_id="eolo-schwab-agent",
            )

    def test_posts_to_correct_oauth_url(self):
        with _build_client_with_mocks() as (client, _, _, _, mock_post):
            client._refresh_access_token()
            args, _ = mock_post.call_args
            assert args[0] == "https://api.schwabapi.com/v1/oauth/token"

    def test_basic_auth_header_format(self):
        with _build_client_with_mocks() as (client, _, _, _, mock_post):
            client._refresh_access_token()
            headers = mock_post.call_args.kwargs["headers"]
            assert headers["Authorization"].startswith("Basic ")
            encoded = headers["Authorization"][len("Basic "):]
            assert base64.b64decode(encoded).decode() == "ak:as"

    def test_payload_grant_type_refresh_token(self):
        with _build_client_with_mocks() as (client, _, _, _, mock_post):
            client._refresh_access_token()
            payload = mock_post.call_args.kwargs["data"]
            assert payload["grant_type"] == "refresh_token"
            assert payload["refresh_token"] == "current_refresh_token"


# ── TestRefreshErrorPaths ─────────────────────────────────────────────────────

class TestRefreshErrorPaths:

    def test_raises_when_firestore_returns_none(self):
        with _build_client_with_mocks(refresh_token=None) as (client, _, _, mock_set, mock_post):
            with pytest.raises(SchwabAuthError, match="No refresh_token in Firestore"):
                client._refresh_access_token()
            mock_post.assert_not_called()
            mock_set.assert_not_called()

    def test_raises_when_schwab_returns_non_200(self):
        with _build_client_with_mocks(
            schwab_status=401,
            schwab_response={"error": "invalid_grant"},
        ) as (client, _, _, mock_set, _):
            with pytest.raises(SchwabAuthError, match="401"):
                client._refresh_access_token()
            mock_set.assert_not_called()

    def test_raises_when_response_missing_access_token(self):
        bad = {"refresh_token": "rt", "expires_in": 1800}
        with _build_client_with_mocks(schwab_response=bad) as (client, _, _, mock_set, _):
            with pytest.raises(SchwabAuthError, match="missing required fields"):
                client._refresh_access_token()
            mock_set.assert_not_called()

    def test_raises_when_response_missing_refresh_token(self):
        bad = {"access_token": "at", "expires_in": 1800}
        with _build_client_with_mocks(schwab_response=bad) as (client, *_):
            with pytest.raises(SchwabAuthError, match="missing required fields"):
                client._refresh_access_token()

    def test_raises_when_response_missing_expires_in(self):
        bad = {"access_token": "at", "refresh_token": "rt"}
        with _build_client_with_mocks(schwab_response=bad) as (client, *_):
            with pytest.raises(SchwabAuthError, match="missing required fields"):
                client._refresh_access_token()

    def test_does_not_persist_to_firestore_on_error(self):
        # Beyond the persistence guards in the firestore-None / 401 / missing-field
        # tests above, this covers the generic "any error path → no persist".
        with _build_client_with_mocks(schwab_response={"foo": "bar"}) as (client, _, _, mock_set, _):
            with pytest.raises(SchwabAuthError):
                client._refresh_access_token()
            mock_set.assert_not_called()


# ── TestRefreshConcurrency ────────────────────────────────────────────────────

class TestRefreshConcurrency:

    def test_lock_has_acquire_release_and_context_manager_protocol(self):
        # threading.Lock() returns _thread.lock — not a class to isinstance-check.
        # Duck-type the protocol: it has acquire(), release(), __enter__, __exit__.
        creds = SchwabCredentials(api_key="ak", api_secret="as")
        client = SchwabClient(credentials=creds)
        assert hasattr(client._refresh_lock, "acquire")
        assert hasattr(client._refresh_lock, "release")
        assert hasattr(client._refresh_lock, "__enter__")
        assert hasattr(client._refresh_lock, "__exit__")
        # Same factory type as threading.Lock() produces.
        assert type(client._refresh_lock) is type(threading.Lock())

    def test_lock_acquired_during_refresh(self):
        with _build_client_with_mocks() as (client, *_):
            # Replace the real lock with a MagicMock to spy on context-manager use.
            lock_spy = MagicMock()
            client._refresh_lock = lock_spy
            client._refresh_access_token()
            lock_spy.__enter__.assert_called_once()
            lock_spy.__exit__.assert_called_once()


# ── TestEnsureAuthenticatedIntegration ────────────────────────────────────────

class TestEnsureAuthenticatedIntegration:

    def test_calls_refresh_when_access_token_none(self):
        with _build_client_with_mocks() as (client, *_):
            assert client.credentials.access_token is None  # baseline
            client._ensure_authenticated()
            assert client.credentials.access_token == "new_access_token_value"

    def test_calls_refresh_when_expired(self):
        with _build_client_with_mocks() as (client, *_):
            client.credentials.access_token = "stale_token"
            client.credentials.token_expires_at = time.time() - 100  # expired
            client._ensure_authenticated()
            assert client.credentials.access_token == "new_access_token_value"

    def test_skips_refresh_when_valid_token(self):
        with _build_client_with_mocks() as (client, _, _, _, mock_post):
            client.credentials.access_token = "still_valid"
            client.credentials.token_expires_at = time.time() + 600  # 10min future
            client._ensure_authenticated()
            mock_post.assert_not_called()
            assert client.credentials.access_token == "still_valid"
