"""Coinbase Advanced Trade authentication via HMAC-SHA256 signing."""

from __future__ import annotations

import hashlib
import hmac
import os
import time


def sign_request(
    api_key: str,
    api_secret: str,
    method: str,
    path: str,
    body: str = "",
) -> dict[str, str]:
    """Build authenticated headers for a Coinbase Advanced Trade request.

    The signature is computed as:
        HMAC-SHA256(timestamp + method + path + body, api_secret)

    Parameters
    ----------
    api_key : str
        Coinbase API key.
    api_secret : str
        Coinbase API secret (hex-encoded or raw string).
    method : str
        HTTP method (GET, POST, DELETE, ...).
    path : str
        Request path **without** the base URL, e.g. ``/api/v3/brokerage/accounts``.
    body : str
        Serialised request body (empty string for GET requests).

    Returns
    -------
    dict[str, str]
        Headers dict containing CB-ACCESS-KEY, CB-ACCESS-SIGN, and
        CB-ACCESS-TIMESTAMP ready to be merged into the request.
    """
    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + path + body
    signature = hmac.new(
        api_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "CB-ACCESS-KEY": api_key,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
    }


def load_credentials() -> tuple[str, str]:
    """Load API key and secret from environment variables.

    Returns
    -------
    tuple[str, str]
        ``(api_key, api_secret)`` read from ``COINBASE_API_KEY`` and
        ``COINBASE_API_SECRET``.

    Raises
    ------
    EnvironmentError
        If either variable is missing or empty.
    """
    api_key = os.environ.get("COINBASE_API_KEY", "")
    api_secret = os.environ.get("COINBASE_API_SECRET", "")
    if not api_key or not api_secret:
        raise EnvironmentError(
            "Both COINBASE_API_KEY and COINBASE_API_SECRET environment "
            "variables must be set."
        )
    return api_key, api_secret
