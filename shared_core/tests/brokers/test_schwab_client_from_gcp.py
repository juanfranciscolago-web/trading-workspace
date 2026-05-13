"""
Unit tests for SchwabClient.from_gcp() factory.

Verifies the GCP-backed construction path (canonical post-S.5.6b):
    - app_creds read from Secret Manager.
    - tokens read from Firestore (full doc, not single key).
    - SchwabAuthError raised if Firestore doc absent.
    - token_expires_at initialized to None (relies on 401 retry path).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from shared_core.brokers.schwab_client import (
    SchwabAuthError,
    SchwabClient,
)


# ── TestFromGcp ───────────────────────────────────────────────────────────────

class TestFromGcp:

    @patch("shared_core.brokers.schwab_client.retrieve_firestore_dict")
    @patch("shared_core.brokers.schwab_client.retrieve_google_secret_dict")
    def test_reads_app_creds_from_secret_manager(
        self,
        mock_secret,
        mock_firestore,
    ):
        mock_secret.return_value = {"app-key": "ak", "app-secret": "as"}
        mock_firestore.return_value = {
            "access_token": "at", "refresh_token": "rt",
        }

        SchwabClient.from_gcp()

        mock_secret.assert_called_once_with(
            gcp_id="eolo-schwab-agent",
            secret_id="cs-app-key",
        )

    @patch("shared_core.brokers.schwab_client.retrieve_firestore_dict")
    @patch("shared_core.brokers.schwab_client.retrieve_google_secret_dict")
    def test_reads_tokens_from_firestore(
        self,
        mock_secret,
        mock_firestore,
    ):
        mock_secret.return_value = {"app-key": "ak", "app-secret": "as"}
        mock_firestore.return_value = {
            "access_token": "at-from-firestore",
            "refresh_token": "rt-from-firestore",
        }

        client = SchwabClient.from_gcp()

        mock_firestore.assert_called_once_with(
            collection_id="schwab-tokens",
            document_id="schwab-tokens-auth",
            project_id="eolo-schwab-agent",
        )
        assert client.credentials.access_token == "at-from-firestore"
        assert client.credentials.refresh_token == "rt-from-firestore"

    @patch("shared_core.brokers.schwab_client.retrieve_firestore_dict")
    @patch("shared_core.brokers.schwab_client.retrieve_google_secret_dict")
    def test_raises_when_firestore_lacks_tokens(
        self,
        mock_secret,
        mock_firestore,
    ):
        mock_secret.return_value = {"app-key": "ak", "app-secret": "as"}
        mock_firestore.return_value = None  # doc missing

        with pytest.raises(SchwabAuthError, match="No tokens in Firestore"):
            SchwabClient.from_gcp()

    @patch("shared_core.brokers.schwab_client.retrieve_firestore_dict")
    @patch("shared_core.brokers.schwab_client.retrieve_google_secret_dict")
    def test_token_expires_at_is_none_initially(
        self,
        mock_secret,
        mock_firestore,
    ):
        # Schwab's response stores `expires_in` (relative); we don't persist
        # absolute expiry. from_gcp sets token_expires_at=None and relies on
        # the 401-retry path in get_X methods to refresh stale tokens.
        mock_secret.return_value = {"app-key": "ak", "app-secret": "as"}
        mock_firestore.return_value = {
            "access_token": "at", "refresh_token": "rt",
        }

        client = SchwabClient.from_gcp()

        assert client.credentials.token_expires_at is None
