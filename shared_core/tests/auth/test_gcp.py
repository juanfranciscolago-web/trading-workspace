"""
Unit tests for shared_core.auth.gcp helpers — Secret Manager + Firestore.

GCP clients are mocked at the class level inside shared_core.auth.gcp:
    - shared_core.auth.gcp.secretmanager.SecretManagerServiceClient
    - shared_core.auth.gcp.firestore.Client

Helpers are kept inline per test class — no shared conftest/fixtures.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from shared_core.auth.gcp import (
    retrieve_firestore_value,
    retrieve_google_secret_dict,
    store_firestore_value,
)


# ── retrieve_google_secret_dict ───────────────────────────────────────────────

class TestRetrieveGoogleSecretDict:

    @patch("shared_core.auth.gcp.secretmanager.SecretManagerServiceClient")
    def test_returns_parsed_dict_on_success(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.payload.data = b'{"app-key": "k", "app-secret": "s"}'
        mock_client_cls.return_value.access_secret_version.return_value = mock_response

        result = retrieve_google_secret_dict(gcp_id="proj", secret_id="sec")

        assert result == {"app-key": "k", "app-secret": "s"}

    @patch("shared_core.auth.gcp.secretmanager.SecretManagerServiceClient")
    def test_constructs_correct_secret_path(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.payload.data = b"{}"
        mock_client_cls.return_value.access_secret_version.return_value = mock_response

        retrieve_google_secret_dict(gcp_id="my-proj", secret_id="my-sec", version_id="3")

        mock_client_cls.return_value.access_secret_version.assert_called_once_with(
            request={"name": "projects/my-proj/secrets/my-sec/versions/3"}
        )

    @patch("shared_core.auth.gcp.secretmanager.SecretManagerServiceClient")
    def test_default_version_id_is_latest(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.payload.data = b"{}"
        mock_client_cls.return_value.access_secret_version.return_value = mock_response

        retrieve_google_secret_dict(gcp_id="p", secret_id="s")

        call = mock_client_cls.return_value.access_secret_version.call_args
        assert call.kwargs["request"]["name"].endswith("/versions/latest")

    @patch("shared_core.auth.gcp.secretmanager.SecretManagerServiceClient")
    def test_raises_on_invalid_json(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.payload.data = b"not valid json {{{"
        mock_client_cls.return_value.access_secret_version.return_value = mock_response

        with pytest.raises(json.JSONDecodeError):
            retrieve_google_secret_dict(gcp_id="p", secret_id="s")


# ── retrieve_firestore_value ──────────────────────────────────────────────────

class TestRetrieveFirestoreValue:

    @patch("shared_core.auth.gcp.firestore.Client")
    def test_returns_value_when_doc_exists(self, mock_client_cls):
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.get.return_value = "the-refresh-token-value"
        (
            mock_client_cls.return_value
            .collection.return_value
            .document.return_value
            .get.return_value
        ) = mock_doc

        result = retrieve_firestore_value(
            collection_id="schwab-tokens",
            document_id="schwab-tokens-auth",
            key="refresh_token",
        )

        assert result == "the-refresh-token-value"
        mock_doc.get.assert_called_once_with("refresh_token")

    @patch("shared_core.auth.gcp.firestore.Client")
    def test_returns_none_when_doc_does_not_exist(self, mock_client_cls):
        mock_doc = MagicMock()
        mock_doc.exists = False
        (
            mock_client_cls.return_value
            .collection.return_value
            .document.return_value
            .get.return_value
        ) = mock_doc

        result = retrieve_firestore_value(
            collection_id="c", document_id="d", key="k",
        )

        assert result is None

    @patch("shared_core.auth.gcp.firestore.Client")
    def test_returns_none_on_client_exception(self, mock_client_cls, caplog):
        # Any Exception raised inside the try is swallowed → None returned.
        # logger.exception records ERROR with exc_info attached.
        mock_client_cls.return_value.collection.side_effect = ValueError("boom")

        with caplog.at_level(logging.ERROR, logger="shared_core.auth.gcp"):
            result = retrieve_firestore_value(
                collection_id="c", document_id="d", key="k",
            )

        assert result is None
        assert any("Failed to retrieve" in r.message for r in caplog.records)
        assert any(r.exc_info is not None for r in caplog.records)

    @patch("shared_core.auth.gcp.firestore.Client")
    def test_uses_project_id_when_provided(self, mock_client_cls):
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.get.return_value = "v"
        (
            mock_client_cls.return_value
            .collection.return_value
            .document.return_value
            .get.return_value
        ) = mock_doc

        retrieve_firestore_value(
            collection_id="c", document_id="d", key="k",
            project_id="my-project",
        )

        mock_client_cls.assert_called_once_with(project="my-project")

    @patch("shared_core.auth.gcp.firestore.Client")
    def test_uses_default_client_when_no_project_id(self, mock_client_cls):
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.get.return_value = "v"
        (
            mock_client_cls.return_value
            .collection.return_value
            .document.return_value
            .get.return_value
        ) = mock_doc

        retrieve_firestore_value(collection_id="c", document_id="d", key="k")

        mock_client_cls.assert_called_once_with()  # no kwargs → ADC default


# ── store_firestore_value ─────────────────────────────────────────────────────

class TestStoreFirestoreValue:

    @patch("shared_core.auth.gcp.firestore.Client")
    def test_writes_dict_to_document(self, mock_client_cls):
        mock_set = (
            mock_client_cls.return_value
            .collection.return_value
            .document.return_value
            .set
        )
        value = {"access_token": "a", "refresh_token": "r", "expires_in": 1800}

        store_firestore_value(
            project_id="proj", collection_id="coll",
            document_id="doc", value=value,
        )

        mock_set.assert_called_once_with(value)

    @patch("shared_core.auth.gcp.firestore.Client")
    def test_uses_set_for_full_overwrite(self, mock_client_cls):
        # .set() replaces whole doc; .update() merges. Verify .set() (overwrite).
        mock_doc_ref = (
            mock_client_cls.return_value
            .collection.return_value
            .document.return_value
        )

        store_firestore_value(
            project_id="p", collection_id="c", document_id="d", value={},
        )

        mock_doc_ref.set.assert_called_once()
        mock_doc_ref.update.assert_not_called()

    @patch("shared_core.auth.gcp.firestore.Client")
    def test_constructs_correct_doc_path(self, mock_client_cls):
        store_firestore_value(
            project_id="my-proj",
            collection_id="my-coll",
            document_id="my-doc",
            value={"k": "v"},
        )

        mock_client_cls.assert_called_once_with(project="my-proj")
        mock_client_cls.return_value.collection.assert_called_once_with("my-coll")
        (
            mock_client_cls.return_value
            .collection.return_value
            .document
            .assert_called_once_with("my-doc")
        )
