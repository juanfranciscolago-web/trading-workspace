"""
GCP auth helpers — Secret Manager + Firestore CRUD.

Ported from Eolo helpers.py (root, 52 LOC). Used by SchwabClient._refresh_access_token
and any other code that needs to read/write the Schwab token document.

Pattern is unchanged from Eolo to preserve compatibility:
    - One-time OAuth dance (init_auth.py / safe_init_auth_v2.py) writes the
      initial token dict to Firestore: schwab-tokens/schwab-tokens-auth.
    - SchwabClient._refresh_access_token reads refresh_token from Firestore,
      POSTs to Schwab /oauth/token, writes the new dict back to Firestore.
    - Schwab rotates BOTH access_token AND refresh_token on each refresh;
      the full dict replacement preserves this invariant.

Auth mechanism (Python google-cloud libs auto-detect):
    - Local dev:  ADC via `gcloud auth application-default login`
                  (~/.config/gcloud/application_default_credentials.json).
    - Cloud Run / CI:  GOOGLE_APPLICATION_CREDENTIALS pointing to SA JSON.
"""

from __future__ import annotations

import json
import logging

from google.cloud import firestore, secretmanager

logger = logging.getLogger(__name__)


def retrieve_google_secret_dict(
    gcp_id: str,
    secret_id: str,
    version_id: str = "latest",
) -> dict:
    """Read a JSON-encoded secret from GCP Secret Manager.

    Args:
        gcp_id: GCP project id (e.g. "eolo-schwab-agent").
        secret_id: Secret name in Secret Manager.
        version_id: Version label or number.

    Returns:
        Parsed dict from the secret's JSON payload.

    Raises:
        google.api_core.exceptions.NotFound: If the secret does not exist.
        json.JSONDecodeError: If the payload is not valid JSON.
    """
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{gcp_id}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    payload = response.payload.data.decode("UTF-8")
    logger.debug("Retrieved secret %s/%s version=%s", gcp_id, secret_id, version_id)
    return json.loads(payload)


def retrieve_firestore_value(
    collection_id: str,
    document_id: str,
    key: str,
    project_id: str | None = None,
) -> str | None:
    """Read a single key from a Firestore document.

    Returns None if the document is missing, the key is absent, or the read
    fails — matches Eolo behavior where callers treat None as "not yet
    initialized" (first run before init_auth has been executed).

    Args:
        collection_id: Firestore collection.
        document_id: Document id within the collection.
        key: Field name inside the document.
        project_id: Optional GCP project. None uses ADC quota_project default
            (matches Eolo's `firestore.Client()` usage in retrieve_firestore_value).

    Returns:
        Field value, or None on miss or read error.
    """
    db = firestore.Client(project=project_id) if project_id else firestore.Client()
    try:
        doc = db.collection(collection_id).document(document_id).get()
        if doc.exists:
            return doc.get(key)
        logger.warning(
            "Firestore document %s/%s does not exist (key=%s)",
            collection_id, document_id, key,
        )
        return None
    except Exception:
        logger.exception(
            "Failed to retrieve %s from Firestore %s/%s",
            key, collection_id, document_id,
        )
        return None


def store_firestore_value(
    project_id: str,
    collection_id: str,
    document_id: str,
    value: dict,
) -> None:
    """Overwrite a Firestore document with the provided dict.

    Used for Schwab token rotation: after each /oauth/token call, Schwab
    returns a new dict (access_token + new refresh_token + expires_in + ...).
    The full document is replaced atomically (Firestore .set() semantics).

    Args:
        project_id: GCP project (explicit since this is a write).
        collection_id: Firestore collection.
        document_id: Document id (will be created if absent).
        value: Dict to write. Replaces any existing document content.
    """
    db = firestore.Client(project=project_id)
    db.collection(collection_id).document(document_id).set(value)
    logger.debug(
        "Wrote Firestore document %s/%s/%s",
        project_id, collection_id, document_id,
    )
