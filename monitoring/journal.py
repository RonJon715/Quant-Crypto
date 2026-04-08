"""Trade journal – logs every engine cycle, trade, and fill as JSONL.

Files are organised by date under the journal directory:
    logs/journal_2026-04-08.jsonl
    logs/trades_2026-04-08.jsonl
    logs/fills_2026-04-08.jsonl

Each line is a self-contained JSON object so files can be tailed, grepped,
and loaded incrementally without parsing a full array.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _utc_today() -> str:
    """Return today's date string in UTC, e.g. '2026-04-08'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _ts() -> float:
    """Current unix timestamp."""
    return time.time()


class TradeJournal:
    """Append-only trade journal backed by JSONL files on disk.

    Three streams are maintained:

    * **cycles** – one record per engine tick (signal weights, mega-alpha,
      edge estimates, portfolio snapshot).
    * **trades** – one record per order sent (asset, side, qty, price,
      signal context at entry).
    * **fills** – one record per confirmed fill from the exchange.
    """

    def __init__(self, journal_dir: str = "logs") -> None:
        self.journal_dir = Path(journal_dir)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        # In-memory buffer for quick queries within the current session
        self._cycles: list[dict[str, Any]] = []
        self._trades: list[dict[str, Any]] = []
        self._fills: list[dict[str, Any]] = []

    # ── private helpers ───────────────────────────────────────────────

    def _jsonl_path(self, prefix: str, date: str | None = None) -> Path:
        date = date or _utc_today()
        return self.journal_dir / f"{prefix}_{date}.jsonl"

    def _append(self, prefix: str, record: dict[str, Any]) -> None:
        """Append *record* to the day's JSONL file and the in-memory list."""
        record.setdefault("ts", _ts())
        record.setdefault("date", _utc_today())
        path = self._jsonl_path(prefix, record["date"])
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except OSError:
            logger.exception("Failed to write journal entry to %s", path)
        # keep in memory
        if prefix == "journal":
            self._cycles.append(record)
        elif prefix == "trades":
            self._trades.append(record)
        elif prefix == "fills":
            self._fills.append(record)

    def _load_jsonl(self, path: Path) -> list[dict[str, Any]]:
        """Load all records from a JSONL file."""
        entries: list[dict[str, Any]] = []
        if not path.exists():
            return entries
        with path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Corrupt JSON on line %d of %s", lineno, path)
        return entries

    # ── public logging API ────────────────────────────────────────────

    def log_cycle(self, cycle_data: dict[str, Any]) -> None:
        """Log a full engine cycle.

        Expected keys (all optional – the journal stores whatever is given):
            signal_weights  – dict[str, float]
            mega_alpha      – dict[str, float]   (per asset)
            edge_estimates  – dict[str, float]
            position_deltas – dict[str, float]
            portfolio       – dict with equity, positions, exposure, etc.
        """
        record: dict[str, Any] = {
            "type": "cycle",
            "ts": _ts(),
            "date": _utc_today(),
        }
        record.update(cycle_data)
        self._append("journal", record)
        logger.debug("Logged engine cycle at %.3f", record["ts"])

    def log_trade(self, trade_data: dict[str, Any]) -> None:
        """Log an individual trade / order submission.

        Expected keys:
            asset, side, qty, price, fill_price, slippage,
            signal_weights_at_entry, mega_alpha_at_entry
        """
        record: dict[str, Any] = {
            "type": "trade",
            "ts": _ts(),
            "date": _utc_today(),
        }
        record.update(trade_data)
        # Compute slippage if both price and fill_price are present
        if (
            "slippage" not in record
            and "price" in record
            and "fill_price" in record
            and record["price"]
        ):
            record["slippage"] = (
                (record["fill_price"] - record["price"]) / record["price"]
            )
        self._append("trades", record)
        logger.info(
            "Trade logged: %s %s %.6f @ %.4f",
            record.get("side", "?"),
            record.get("asset", "?"),
            record.get("qty", 0.0),
            record.get("fill_price", record.get("price", 0.0)),
        )

    def log_fill(self, fill_data: dict[str, Any]) -> None:
        """Log an order fill confirmation from the exchange.

        Expected keys:
            order_id, asset, side, qty, price, fee, exchange_ts
        """
        record: dict[str, Any] = {
            "type": "fill",
            "ts": _ts(),
            "date": _utc_today(),
        }
        record.update(fill_data)
        self._append("fills", record)
        logger.info(
            "Fill logged: order=%s %s %s %.6f @ %.4f",
            record.get("order_id", "?"),
            record.get("side", "?"),
            record.get("asset", "?"),
            record.get("qty", 0.0),
            record.get("price", 0.0),
        )

    # ── query / export ────────────────────────────────────────────────

    def _collect_entries(
        self,
        prefix: str,
        days: int,
        in_memory: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Gather entries from disk for the last *days* days, then merge
        with any in-memory entries that might not have been flushed yet."""
        seen_ts: set[float] = set()
        entries: list[dict[str, Any]] = []

        now = datetime.now(timezone.utc)
        for day_offset in range(days):
            dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            dt = dt.__class__(
                dt.year, dt.month, dt.day, tzinfo=timezone.utc
            )
            from datetime import timedelta

            target = dt - timedelta(days=day_offset)
            date_str = target.strftime("%Y-%m-%d")
            path = self._jsonl_path(prefix, date_str)
            for rec in self._load_jsonl(path):
                ts = rec.get("ts", 0.0)
                if ts not in seen_ts:
                    seen_ts.add(ts)
                    entries.append(rec)

        # merge in-memory entries that may not be on disk yet
        for rec in in_memory:
            ts = rec.get("ts", 0.0)
            if ts not in seen_ts:
                seen_ts.add(ts)
                entries.append(rec)

        entries.sort(key=lambda r: r.get("ts", 0.0))
        return entries

    def get_trades(self, days: int = 7) -> list[dict[str, Any]]:
        """Return trade records from the last *days* days."""
        return self._collect_entries("trades", days, self._trades)

    def get_fills(self, days: int = 7) -> list[dict[str, Any]]:
        """Return fill records from the last *days* days."""
        return self._collect_entries("fills", days, self._fills)

    def get_cycles(self, days: int = 7) -> list[dict[str, Any]]:
        """Return engine cycle records from the last *days* days."""
        return self._collect_entries("journal", days, self._cycles)

    def export_csv(self, filepath: str | None = None) -> str:
        """Export all trade entries to CSV.  Returns the CSV as a string and
        optionally writes to *filepath*."""
        trades = self.get_trades(days=365)
        if not trades:
            logger.warning("No trades to export")
            return ""

        # Collect all keys across trades for the header
        all_keys: list[str] = []
        key_set: set[str] = set()
        # Guarantee a sensible column order
        priority = [
            "date", "ts", "type", "asset", "side", "qty",
            "price", "fill_price", "slippage",
            "signal_weights_at_entry", "mega_alpha_at_entry",
        ]
        for k in priority:
            if any(k in t for t in trades):
                all_keys.append(k)
                key_set.add(k)
        for t in trades:
            for k in t:
                if k not in key_set:
                    all_keys.append(k)
                    key_set.add(k)

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        for t in trades:
            # Flatten nested dicts to JSON strings for CSV cells
            row = {}
            for k in all_keys:
                val = t.get(k, "")
                if isinstance(val, (dict, list)):
                    val = json.dumps(val, default=str)
                row[k] = val
            writer.writerow(row)

        csv_text = buf.getvalue()

        if filepath:
            out_path = Path(filepath)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(csv_text, encoding="utf-8")
            logger.info("Exported %d trades to %s", len(trades), filepath)

        return csv_text

    def get_summary(self, days: int = 7) -> dict[str, Any]:
        """Return summary statistics over the last *days* days.

        Keys returned:
            total_trades, total_fills, win_rate, avg_slippage_bps,
            gross_pnl, net_pnl, largest_win, largest_loss,
            assets_traded, first_trade_ts, last_trade_ts.
        """
        trades = self.get_trades(days=days)
        fills = self.get_fills(days=days)

        summary: dict[str, Any] = {
            "days": days,
            "total_trades": len(trades),
            "total_fills": len(fills),
            "win_rate": 0.0,
            "avg_slippage_bps": 0.0,
            "gross_pnl": 0.0,
            "net_pnl": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
            "assets_traded": [],
            "first_trade_ts": None,
            "last_trade_ts": None,
        }

        if not trades:
            return summary

        slippages: list[float] = []
        pnls: list[float] = []
        assets: set[str] = set()

        for t in trades:
            if "slippage" in t and t["slippage"] is not None:
                slippages.append(float(t["slippage"]))
            if "pnl" in t and t["pnl"] is not None:
                pnls.append(float(t["pnl"]))
            if "asset" in t:
                assets.add(t["asset"])

        summary["assets_traded"] = sorted(assets)
        summary["first_trade_ts"] = trades[0].get("ts")
        summary["last_trade_ts"] = trades[-1].get("ts")

        if slippages:
            summary["avg_slippage_bps"] = round(
                sum(slippages) / len(slippages) * 10_000, 4,
            )

        if pnls:
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            summary["gross_pnl"] = round(sum(pnls), 8)
            summary["net_pnl"] = round(sum(pnls), 8)  # fees handled elsewhere
            summary["win_rate"] = round(len(wins) / len(pnls), 4) if pnls else 0.0
            summary["largest_win"] = round(max(wins), 8) if wins else 0.0
            summary["largest_loss"] = round(min(losses), 8) if losses else 0.0

        return summary
