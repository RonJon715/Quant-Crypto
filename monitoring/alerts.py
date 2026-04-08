"""Alert delivery via Telegram and Discord.

Alerts are best-effort: a failed delivery logs a warning but never raises
or crashes the bot.  All public methods are ``async`` so they integrate
naturally with the asyncio engine loop.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Mapping from level name to emoji prefix for readability in chat apps.
_LEVEL_PREFIX: dict[str, str] = {
    "info": "ℹ️",
    "warning": "⚠️",
    "error": "🚨",
    "critical": "🔴",
    "success": "✅",
}

_TELEGRAM_API = "https://api.telegram.org"
_HTTP_TIMEOUT = 10.0  # seconds


class AlertManager:
    """Multi-channel alert dispatcher.

    Channels are configured at construction or via environment variables:

    * **Telegram** – ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``
    * **Discord**  – ``DISCORD_WEBHOOK_URL``

    If a channel's credentials are missing it is silently skipped.
    """

    def __init__(
        self,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        discord_webhook_url: str = "",
    ) -> None:
        self.telegram_token = telegram_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.discord_webhook_url = discord_webhook_url or os.getenv(
            "DISCORD_WEBHOOK_URL", ""
        )

        self._telegram_enabled = bool(self.telegram_token and self.telegram_chat_id)
        self._discord_enabled = bool(self.discord_webhook_url)

        if not self._telegram_enabled and not self._discord_enabled:
            logger.warning(
                "AlertManager: no channels configured – alerts will only be logged"
            )

    # ── core delivery ─────────────────────────────────────────────────

    async def send_alert(self, message: str, level: str = "info") -> None:
        """Send *message* to every configured channel.

        *level* should be one of ``info``, ``warning``, ``error``,
        ``critical``, ``success``.  It is used for log level selection and
        to prefix the message with an appropriate emoji.
        """
        prefix = _LEVEL_PREFIX.get(level, "")
        full_message = f"{prefix} [{level.upper()}] {message}"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        full_message += f"\n{ts}"

        # Always log locally regardless of channel availability
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(log_level, "Alert: %s", message)

        # Fire to all channels concurrently-ish (sequential is fine here –
        # we don't want one channel's timeout to block the other for 10 s,
        # but httpx is fast enough for a best-effort alert).
        if self._telegram_enabled:
            await self._send_telegram(full_message)
        if self._discord_enabled:
            await self._send_discord(full_message)

    async def _send_telegram(self, message: str) -> None:
        """Deliver a message via Telegram Bot API."""
        url = f"{_TELEGRAM_API}/bot{self.telegram_token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    logger.warning(
                        "Telegram alert failed (HTTP %d): %s",
                        resp.status_code,
                        resp.text[:200],
                    )
        except httpx.HTTPError as exc:
            logger.warning("Telegram alert failed: %s", exc)
        except Exception:
            logger.warning("Telegram alert failed with unexpected error", exc_info=True)

    async def _send_discord(self, message: str) -> None:
        """Deliver a message via Discord webhook."""
        payload: dict[str, Any] = {"content": message}
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(self.discord_webhook_url, json=payload)
                # Discord returns 204 on success
                if resp.status_code not in (200, 204):
                    logger.warning(
                        "Discord alert failed (HTTP %d): %s",
                        resp.status_code,
                        resp.text[:200],
                    )
        except httpx.HTTPError as exc:
            logger.warning("Discord alert failed: %s", exc)
        except Exception:
            logger.warning("Discord alert failed with unexpected error", exc_info=True)

    # ── convenience methods ───────────────────────────────────────────

    async def alert_fill(
        self,
        asset: str,
        side: str,
        qty: float,
        price: float,
    ) -> None:
        """Alert on an order fill."""
        msg = (
            f"<b>Fill</b>: {side.upper()} {qty:.6f} {asset} @ {price:,.4f}"
        )
        await self.send_alert(msg, level="info")

    async def alert_error(self, error: str) -> None:
        """Alert on a bot error."""
        msg = f"<b>Error</b>: {error}"
        await self.send_alert(msg, level="error")

    async def alert_regime_change(self, old_regime: str, new_regime: str) -> None:
        """Alert when the market regime detector changes state."""
        msg = (
            f"<b>Regime change</b>: {old_regime} -> {new_regime}"
        )
        await self.send_alert(msg, level="warning")

    async def alert_drawdown(self, drawdown_pct: float, period: str) -> None:
        """Alert when drawdown exceeds a threshold."""
        level = "critical" if drawdown_pct < -10 else "warning"
        msg = (
            f"<b>Drawdown alert</b>: {drawdown_pct:+.2f}% over {period}"
        )
        await self.send_alert(msg, level=level)

    async def alert_circuit_breaker(self, breaker: str, action: str) -> None:
        """Alert when a circuit breaker trips or resets."""
        level = "critical" if action.lower() in ("tripped", "triggered") else "info"
        msg = (
            f"<b>Circuit breaker</b>: {breaker} — {action}"
        )
        await self.send_alert(msg, level=level)
