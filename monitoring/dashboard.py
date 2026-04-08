"""Terminal dashboard using the *rich* library.

Provides both a live-updating display (``start_live``) and a one-shot
snapshot (``print_snapshot``).  The layout is divided into four panels:

* **Portfolio** – positions, equity, exposure, drawdown
* **Signals**   – current weights / values / staleness
* **Trades**    – last N fills
* **Risk**      – circuit breaker status, VPIN level, limits
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def _fmt_ts(ts: float | int | None) -> str:
    """Format a unix timestamp to human-readable UTC string."""
    if ts is None:
        return "-"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.2f}%"


def _fmt_usd(value: float | None) -> str:
    if value is None:
        return "-"
    return f"${value:,.2f}"


def _colour_pnl(value: float) -> str:
    """Return a rich colour tag string for a P&L value."""
    if value > 0:
        return "green"
    if value < 0:
        return "red"
    return "white"


class Dashboard:
    """Rich-based terminal dashboard for the trading engine."""

    MAX_RECENT_TRADES = 10

    def __init__(self) -> None:
        self.console = Console()
        self._portfolio_data: dict[str, Any] = {}
        self._signal_data: dict[str, Any] = {}
        self._recent_trades: list[dict[str, Any]] = []
        self._risk_status: dict[str, Any] = {}
        self._last_update: float = 0.0

    # ── data ingestion ────────────────────────────────────────────────

    def update(
        self,
        portfolio: dict[str, Any],
        signals: dict[str, Any],
        trades: list[dict[str, Any]],
        risk: dict[str, Any],
    ) -> None:
        """Replace all dashboard data in one call."""
        self._portfolio_data = portfolio
        self._signal_data = signals
        self._recent_trades = trades[-self.MAX_RECENT_TRADES :]
        self._risk_status = risk
        self._last_update = time.time()

    # ── panel builders ────────────────────────────────────────────────

    def _build_portfolio_panel(self) -> Panel:
        data = self._portfolio_data
        table = Table(show_header=True, header_style="bold cyan", expand=True)
        table.add_column("Metric", style="dim")
        table.add_column("Value", justify="right")

        equity = data.get("equity")
        table.add_row("Equity", _fmt_usd(equity))

        cash = data.get("cash")
        table.add_row("Cash", _fmt_usd(cash))

        exposure = data.get("exposure")
        table.add_row("Exposure", _fmt_pct(exposure))

        drawdown = data.get("drawdown_pct")
        dd_style = "red bold" if drawdown is not None and drawdown < -5 else "white"
        table.add_row(
            "Drawdown",
            Text(_fmt_pct(drawdown), style=dd_style),
        )

        unrealised = data.get("unrealised_pnl", 0.0)
        table.add_row(
            "Unrealised P&L",
            Text(_fmt_usd(unrealised), style=_colour_pnl(unrealised)),
        )

        realised = data.get("realised_pnl", 0.0)
        table.add_row(
            "Realised P&L",
            Text(_fmt_usd(realised), style=_colour_pnl(realised)),
        )

        # Positions sub-table
        positions = data.get("positions", {})
        if positions:
            table.add_row("", "")
            table.add_row("[bold]Positions[/bold]", f"[dim]{len(positions)} open[/dim]")
            for asset, pos in positions.items():
                if isinstance(pos, dict):
                    qty = pos.get("qty", 0.0)
                    pnl = pos.get("pnl", 0.0)
                    table.add_row(
                        f"  {asset}",
                        Text(f"{qty:+.6f}  ({_fmt_usd(pnl)})", style=_colour_pnl(pnl)),
                    )
                else:
                    table.add_row(f"  {asset}", f"{pos:+.6f}")

        return Panel(table, title="Portfolio", border_style="blue")

    def _build_signal_panel(self) -> Panel:
        data = self._signal_data
        table = Table(show_header=True, header_style="bold magenta", expand=True)
        table.add_column("Signal", style="dim")
        table.add_column("Weight", justify="right")
        table.add_column("Value", justify="right")
        table.add_column("Stale?", justify="center")

        weights = data.get("weights", {})
        values = data.get("values", {})
        staleness = data.get("staleness", {})

        # Merge all signal names
        all_signals = sorted(
            set(list(weights.keys()) + list(values.keys()) + list(staleness.keys()))
        )

        for sig in all_signals:
            w = weights.get(sig)
            v = values.get(sig)
            is_stale = staleness.get(sig, False)

            w_str = f"{w:.4f}" if w is not None else "-"
            v_str = f"{v:+.4f}" if v is not None else "-"
            stale_str = Text("YES", style="red bold") if is_stale else Text("no", style="green")

            table.add_row(sig, w_str, v_str, stale_str)

        # Mega alpha row if present
        mega_alpha = data.get("mega_alpha")
        if mega_alpha is not None:
            table.add_row("", "", "", "")
            if isinstance(mega_alpha, dict):
                for asset, alpha in mega_alpha.items():
                    table.add_row(
                        f"[bold]mega_alpha[/bold] ({asset})",
                        "",
                        f"{alpha:+.6f}",
                        "",
                    )
            else:
                table.add_row("[bold]mega_alpha[/bold]", "", f"{mega_alpha:+.6f}", "")

        return Panel(table, title="Signals", border_style="magenta")

    def _build_trades_panel(self) -> Panel:
        table = Table(show_header=True, header_style="bold yellow", expand=True)
        table.add_column("Time", style="dim")
        table.add_column("Asset")
        table.add_column("Side", justify="center")
        table.add_column("Qty", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Slip (bps)", justify="right")

        for t in reversed(self._recent_trades):
            ts_str = _fmt_ts(t.get("ts"))
            asset = t.get("asset", "?")
            side = t.get("side", "?")
            qty = t.get("qty", 0.0)
            price = t.get("fill_price", t.get("price", 0.0))
            slippage = t.get("slippage")

            side_style = "green" if side.lower() == "buy" else "red"
            slip_str = f"{slippage * 10_000:.1f}" if slippage is not None else "-"

            table.add_row(
                ts_str,
                asset,
                Text(side.upper(), style=side_style),
                f"{qty:.6f}",
                f"{price:.4f}",
                slip_str,
            )

        if not self._recent_trades:
            table.add_row("-", "-", "-", "-", "-", "-")

        return Panel(table, title="Recent Trades", border_style="yellow")

    def _build_risk_panel(self) -> Panel:
        data = self._risk_status
        table = Table(show_header=True, header_style="bold red", expand=True)
        table.add_column("Check", style="dim")
        table.add_column("Status", justify="center")
        table.add_column("Detail", justify="right")

        # Circuit breakers
        breakers = data.get("circuit_breakers", {})
        for name, state in breakers.items():
            if isinstance(state, dict):
                active = state.get("active", False)
                detail = state.get("detail", "")
            else:
                active = bool(state)
                detail = ""
            status_text = Text("TRIPPED", style="red bold") if active else Text("OK", style="green")
            table.add_row(f"CB: {name}", status_text, str(detail))

        # VPIN
        vpin = data.get("vpin")
        if vpin is not None:
            vpin_style = "red bold" if vpin > 0.8 else ("yellow" if vpin > 0.6 else "green")
            table.add_row("VPIN", Text(f"{vpin:.4f}", style=vpin_style), "")

        # Drawdown limit
        dd_limit = data.get("drawdown_limit_pct")
        dd_current = data.get("drawdown_current_pct")
        if dd_limit is not None:
            usage = (
                abs(dd_current / dd_limit) * 100 if dd_limit and dd_current else 0.0
            )
            table.add_row(
                "Drawdown limit",
                f"{_fmt_pct(dd_current)} / {_fmt_pct(dd_limit)}",
                f"{usage:.0f}% used",
            )

        # Position limits
        pos_limit = data.get("position_limit_pct")
        if pos_limit is not None:
            table.add_row("Position limit", _fmt_pct(pos_limit), "")

        # General status line
        overall = data.get("status", "unknown")
        overall_style = "green bold" if overall == "normal" else "red bold"
        table.add_row("Overall", Text(overall.upper(), style=overall_style), "")

        if not breakers and vpin is None and dd_limit is None:
            table.add_row("No risk data", Text("-", style="dim"), "")

        return Panel(table, title="Risk", border_style="red")

    # ── layout assembly ───────────────────────────────────────────────

    def render(self) -> Layout:
        """Build the full dashboard layout with four panels."""
        layout = Layout()

        # Header
        header_text = Text(
            f"  Quant-Crypto Dashboard  |  "
            f"Last update: {_fmt_ts(self._last_update)}  |  "
            f"UTC: {datetime.now(timezone.utc).strftime('%H:%M:%S')}",
            style="bold white on dark_blue",
        )
        header = Layout(Panel(header_text, style="bold"), size=3)

        # Body: two columns
        body = Layout()
        left = Layout()
        right = Layout()

        left.split_column(
            Layout(self._build_portfolio_panel(), name="portfolio"),
            Layout(self._build_trades_panel(), name="trades"),
        )
        right.split_column(
            Layout(self._build_signal_panel(), name="signals"),
            Layout(self._build_risk_panel(), name="risk"),
        )

        body.split_row(left, right)

        layout.split_column(header, body)
        return layout

    # ── output modes ──────────────────────────────────────────────────

    def start_live(self, refresh_rate: float = 2.0) -> Live:
        """Return a ``rich.live.Live`` context manager for continuous updates.

        Usage::

            live = dashboard.start_live()
            with live:
                while running:
                    dashboard.update(portfolio, signals, trades, risk)
                    live.update(dashboard.render())
                    await asyncio.sleep(refresh_rate)

        Returns the Live object so callers can control the lifecycle.
        """
        live = Live(
            self.render(),
            console=self.console,
            refresh_per_second=1.0 / refresh_rate,
            screen=True,
        )
        return live

    def print_snapshot(self) -> None:
        """Print a single snapshot to the terminal (non-live)."""
        self.console.print(self.render())
