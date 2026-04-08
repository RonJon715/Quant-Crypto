"""Coinbase Advanced Trade WebSocket client with reconnection logic."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

import websockets
import websockets.client

from exchange.auth import load_credentials

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_RECONNECT_BASE = 1.0       # seconds
_RECONNECT_MAX = 60.0       # seconds
_RECONNECT_FACTOR = 2.0


def _ws_sign(api_key: str, api_secret: str, channel: str, product_ids: list[str]) -> dict[str, Any]:
    """Build the authentication fields for a WebSocket subscribe message.

    Coinbase WS auth uses the same HMAC-SHA256 scheme as REST:
        signature = HMAC(timestamp + channel + comma-joined product_ids, secret)
    """
    timestamp = str(int(time.time()))
    message = timestamp + channel + ",".join(product_ids)
    signature = hmac.new(
        api_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "api_key": api_key,
        "timestamp": timestamp,
        "signature": signature,
    }


# Callback type: async or sync function accepting a single dict.
_Callback = Callable[[dict[str, Any]], Any] | Callable[[dict[str, Any]], Coroutine[Any, Any, Any]]


class CoinbaseWebSocket:
    """Async WebSocket manager for Coinbase Advanced Trade live data.

    Supports the ``ticker``, ``level2``, and ``market_trades`` channels with
    automatic reconnection using exponential back-off.

    Usage
    -----
    >>> ws = CoinbaseWebSocket()
    >>> ws.on_ticker(my_ticker_handler)
    >>> await ws.connect()
    >>> await ws.subscribe(["ticker"], ["BTC-USD"])
    """

    WS_URL = "wss://advanced-trade-ws.coinbase.com"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
    ) -> None:
        if not api_key or not api_secret:
            api_key, api_secret = load_credentials()
        self._api_key = api_key
        self._api_secret = api_secret

        self._ws: websockets.client.WebSocketClientProtocol | None = None
        self._running = False
        self._listen_task: asyncio.Task[None] | None = None

        # Per-channel callbacks.
        self._callbacks: dict[str, list[_Callback]] = {
            "ticker": [],
            "level2": [],
            "market_trades": [],
        }

        # Track active subscriptions so we can re-subscribe on reconnect.
        self._subscriptions: list[tuple[list[str], list[str]]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the WebSocket connection and start the listener loop."""
        self._running = True
        await self._open_connection()
        self._listen_task = asyncio.create_task(self._listen())

    async def disconnect(self) -> None:
        """Gracefully close the WebSocket connection."""
        self._running = False
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def subscribe(
        self,
        channels: list[str],
        product_ids: list[str],
    ) -> None:
        """Subscribe to one or more channels for the given product IDs.

        Parameters
        ----------
        channels : list[str]
            Channel names, e.g. ``["ticker", "level2"]``.
        product_ids : list[str]
            Product IDs, e.g. ``["BTC-USD", "ETH-USD"]``.
        """
        # Remember for reconnection.
        self._subscriptions.append((channels, product_ids))
        await self._send_subscribe(channels, product_ids)

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_ticker(self, callback: _Callback) -> None:
        """Register a callback for ``ticker`` channel events."""
        self._callbacks["ticker"].append(callback)

    def on_level2(self, callback: _Callback) -> None:
        """Register a callback for ``level2`` channel events."""
        self._callbacks["level2"].append(callback)

    def on_market_trades(self, callback: _Callback) -> None:
        """Register a callback for ``market_trades`` channel events."""
        self._callbacks["market_trades"].append(callback)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _open_connection(self) -> None:
        """Open a fresh WebSocket connection."""
        logger.info("Opening WebSocket connection to %s", self.WS_URL)
        self._ws = await websockets.connect(self.WS_URL, ping_interval=20)

    async def _send_subscribe(
        self,
        channels: list[str],
        product_ids: list[str],
    ) -> None:
        """Send an authenticated subscribe message over the WebSocket."""
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected")

        for channel in channels:
            auth_fields = _ws_sign(
                self._api_key, self._api_secret, channel, product_ids
            )
            msg = {
                "type": "subscribe",
                "product_ids": product_ids,
                "channel": channel,
                **auth_fields,
            }
            await self._ws.send(json.dumps(msg))
            logger.debug("Subscribed to %s for %s", channel, product_ids)

    async def _listen(self) -> None:
        """Main listener loop with automatic reconnection."""
        delay = _RECONNECT_BASE

        while self._running:
            try:
                async for raw in self._ws:  # type: ignore[union-attr]
                    delay = _RECONNECT_BASE  # reset on successful message
                    try:
                        message: dict[str, Any] = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("Non-JSON WebSocket message: %s", raw[:200])
                        continue
                    await self._dispatch(message)

            except websockets.ConnectionClosed as exc:
                if not self._running:
                    break
                logger.warning(
                    "WebSocket closed (code=%s reason=%s) – reconnecting in %.1fs",
                    exc.code,
                    exc.reason,
                    delay,
                )
            except Exception:
                if not self._running:
                    break
                logger.exception("Unexpected WebSocket error – reconnecting in %.1fs", delay)

            if not self._running:
                break

            await asyncio.sleep(delay)
            delay = min(delay * _RECONNECT_FACTOR, _RECONNECT_MAX)

            try:
                await self._open_connection()
                # Re-subscribe to all previously requested channels.
                for channels, product_ids in self._subscriptions:
                    await self._send_subscribe(channels, product_ids)
            except Exception:
                logger.exception("Reconnection attempt failed")

    async def _dispatch(self, message: dict[str, Any]) -> None:
        """Route an incoming message to the appropriate callbacks."""
        channel = message.get("channel", "")
        callbacks = self._callbacks.get(channel, [])
        for cb in callbacks:
            try:
                result = cb(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Error in %s callback", channel)
