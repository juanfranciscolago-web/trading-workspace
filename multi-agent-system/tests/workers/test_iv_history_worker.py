"""Unit tests for IvHistoryWorker (S.6.iv-c).

All tests inject schwab_client + repo mocks. Worker construction with
missing schwab_client raises TypeError (Opción C — tests safe by default,
no path to real GCP).

asyncio_mode = "auto" en pyproject — async def tests run sin
@pytest.mark.asyncio decorator.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from multi_agent.data_layer.iv_compute import compute_atm_iv
from multi_agent.workers.iv_history_worker import IvHistoryWorker


# Sample chain response (matches Schwab normalized format from S.5.6d)
_SAMPLE_CHAIN = {
    "underlying": "SPY",
    "spot": {"last": 450.0},
    "expirations": ["2026-06-19"],
    "calls": {
        "2026-06-19": {
            "450.0": {"iv": 0.20, "delta": 0.50},
            "455.0": {"iv": 0.22, "delta": 0.30},
        },
    },
    "puts": {
        "2026-06-19": {
            "450.0": {"iv": 0.21, "delta": -0.50},
            "445.0": {"iv": 0.24, "delta": -0.30},
        },
    },
}


# ── Fixture factory ──────────────────────────────────────────────────────────

def _make_worker(
    *,
    chain_response: dict | None = None,
    has_snapshot: bool = False,
    poll_interval_s: float = 0.05,
) -> tuple[IvHistoryWorker, MagicMock, MagicMock]:
    """Build IvHistoryWorker with mock repo + schwab_client.

    Returns (worker, mock_repo, mock_client) for tests to configure.
    Defaults: chain has SPY-shaped fixture, has_snapshot=False.
    """
    mock_repo = MagicMock()
    mock_repo.has_snapshot_today.return_value = has_snapshot

    mock_client = MagicMock()
    mock_client.get_options_chain.return_value = (
        chain_response if chain_response is not None else _SAMPLE_CHAIN
    )

    worker = IvHistoryWorker(
        repo=mock_repo,
        schwab_client=mock_client,
        poll_interval_s=poll_interval_s,
    )
    return worker, mock_repo, mock_client


def _make_datetime_mock(fake_now: datetime):
    """Build a datetime class mock that returns fake_now from now(tz)."""
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now.astimezone(tz) if tz else fake_now
    return _FrozenDatetime


# ── TestComputeAtmIv ─────────────────────────────────────────────────────────

class TestComputeAtmIv:
    """compute_atm_iv pure function — D3 logic isolated (S.6.iv-d)."""

    def test_avg_call_put_at_atm_strike(self):
        # ATM strike 450, call iv=0.20, put iv=0.21 → avg=0.205
        result = compute_atm_iv(_SAMPLE_CHAIN, spot=450.0)
        assert result == pytest.approx(0.205)

    def test_fallback_to_call_only_when_put_missing(self):
        chain = {
            "expirations": ["2026-06-19"],
            "spot": {"last": 450.0},
            "calls": {"2026-06-19": {"450.0": {"iv": 0.20}}},
            "puts": {},
        }
        result = compute_atm_iv(chain, spot=450.0)
        assert result == 0.20

    def test_fallback_to_put_only_when_call_missing(self):
        chain = {
            "expirations": ["2026-06-19"],
            "spot": {"last": 450.0},
            "calls": {},
            "puts": {"2026-06-19": {"450.0": {"iv": 0.24}}},
        }
        result = compute_atm_iv(chain, spot=450.0)
        assert result == 0.24

    def test_returns_none_when_both_zero(self):
        chain = {
            "expirations": ["2026-06-19"],
            "spot": {"last": 450.0},
            "calls": {"2026-06-19": {"450.0": {"iv": 0.0}}},
            "puts": {"2026-06-19": {"450.0": {"iv": 0.0}}},
        }
        result = compute_atm_iv(chain, spot=450.0)
        assert result is None

    def test_returns_none_for_empty_expirations(self):
        chain = {"expirations": [], "spot": {"last": 450.0}}
        result = compute_atm_iv(chain, spot=450.0)
        assert result is None

    def test_returns_none_for_invalid_spot(self):
        result = compute_atm_iv(_SAMPLE_CHAIN, spot=0.0)
        assert result is None


# ── TestShouldSnapshotNow ────────────────────────────────────────────────────

class TestShouldSnapshotNow:
    """_should_snapshot_now predicate — weekend, time gate, canary."""

    def test_returns_false_on_saturday(self, monkeypatch):
        # 2026-05-16 is a Saturday
        fake_now = datetime(2026, 5, 16, 22, 0, tzinfo=timezone.utc)
        worker, _, _ = _make_worker()
        monkeypatch.setattr(
            "multi_agent.workers.iv_history_worker.datetime",
            _make_datetime_mock(fake_now),
        )
        assert worker._should_snapshot_now() is False

    def test_returns_false_on_sunday(self, monkeypatch):
        fake_now = datetime(2026, 5, 17, 22, 0, tzinfo=timezone.utc)
        worker, _, _ = _make_worker()
        monkeypatch.setattr(
            "multi_agent.workers.iv_history_worker.datetime",
            _make_datetime_mock(fake_now),
        )
        assert worker._should_snapshot_now() is False

    def test_returns_false_before_21_15_utc(self, monkeypatch):
        # Thursday 20:00 UTC (before snapshot time)
        fake_now = datetime(2026, 5, 14, 20, 0, tzinfo=timezone.utc)
        worker, _, _ = _make_worker()
        monkeypatch.setattr(
            "multi_agent.workers.iv_history_worker.datetime",
            _make_datetime_mock(fake_now),
        )
        assert worker._should_snapshot_now() is False

    def test_returns_true_after_21_15_no_snapshot_today(self, monkeypatch):
        # Thursday 22:00 UTC, canary SPY not yet snapshotted
        fake_now = datetime(2026, 5, 14, 22, 0, tzinfo=timezone.utc)
        worker, repo, _ = _make_worker(has_snapshot=False)
        monkeypatch.setattr(
            "multi_agent.workers.iv_history_worker.datetime",
            _make_datetime_mock(fake_now),
        )
        assert worker._should_snapshot_now() is True
        repo.has_snapshot_today.assert_called_once_with("SPY", date(2026, 5, 14))

    def test_returns_false_when_canary_already_snapshotted(self, monkeypatch):
        fake_now = datetime(2026, 5, 14, 22, 0, tzinfo=timezone.utc)
        worker, _, _ = _make_worker(has_snapshot=True)
        monkeypatch.setattr(
            "multi_agent.workers.iv_history_worker.datetime",
            _make_datetime_mock(fake_now),
        )
        assert worker._should_snapshot_now() is False


# ── TestSnapshotOneTicker ────────────────────────────────────────────────────

class TestSnapshotOneTicker:
    """_snapshot_one_ticker — single-ticker fetch + persist flow."""

    def test_writes_snapshot_when_chain_valid(self):
        worker, repo, client = _make_worker()
        ts = datetime(2026, 5, 14, 21, 15, tzinfo=timezone.utc)

        worker._snapshot_one_ticker("SPY", ts)

        client.get_options_chain.assert_called_once_with("SPY")
        repo.write_snapshot.assert_called_once()
        kwargs = repo.write_snapshot.call_args.kwargs
        assert kwargs["ticker"] == "SPY"
        assert kwargs["ts"] == ts
        assert kwargs["atm_iv"] == pytest.approx(0.205)
        assert kwargs["underlying_close"] == 450.0

    def test_skips_when_chain_empty(self):
        empty_chain = {"expirations": [], "spot": {"last": 0.0}}
        worker, repo, _ = _make_worker(chain_response=empty_chain)
        ts = datetime(2026, 5, 14, 21, 15, tzinfo=timezone.utc)

        worker._snapshot_one_ticker("SPY", ts)

        repo.write_snapshot.assert_not_called()

    def test_skips_when_atm_iv_uncomputable(self):
        zero_chain = {
            "expirations": ["2026-06-19"],
            "spot": {"last": 450.0},
            "calls": {"2026-06-19": {"450.0": {"iv": 0.0}}},
            "puts": {"2026-06-19": {"450.0": {"iv": 0.0}}},
        }
        worker, repo, _ = _make_worker(chain_response=zero_chain)
        ts = datetime(2026, 5, 14, 21, 15, tzinfo=timezone.utc)

        worker._snapshot_one_ticker("SPY", ts)

        repo.write_snapshot.assert_not_called()


# ── TestSnapshotAllTickers ───────────────────────────────────────────────────

class TestSnapshotAllTickers:
    """_snapshot_all_tickers — per-ticker error isolation (D-γ)."""

    async def test_per_ticker_failure_does_not_block_others(self):
        # Mock get_options_chain to raise for "NVDA" only; succeed for others.
        worker, repo, client = _make_worker()

        def _chain_side_effect(ticker):
            if ticker == "NVDA":
                raise RuntimeError("Simulated NVDA chain fetch failure")
            return _SAMPLE_CHAIN
        client.get_options_chain.side_effect = _chain_side_effect

        await worker._snapshot_all_tickers()

        # 6 tickers, 1 fails → 5 writes.
        assert repo.write_snapshot.call_count == 5
        # Verify NVDA was attempted (get_options_chain called for it)
        called_tickers = {c.args[0] for c in client.get_options_chain.call_args_list}
        assert "NVDA" in called_tickers
        assert len(called_tickers) == 6


# ── TestRunLifecycle ─────────────────────────────────────────────────────────

class TestRunLifecycle:
    """run() + shutdown() async lifecycle."""

    async def test_shutdown_stops_loop(self):
        worker, _, _ = _make_worker(poll_interval_s=10.0)

        async def _stop():
            await asyncio.sleep(0.05)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=2.0),
            _stop(),
        )
        # No exception = clean shutdown.

    async def test_predicate_false_does_not_snapshot(self, monkeypatch):
        # Saturday → predicate False, snapshot never invoked.
        fake_now = datetime(2026, 5, 16, 22, 0, tzinfo=timezone.utc)
        worker, repo, client = _make_worker(poll_interval_s=10.0)
        monkeypatch.setattr(
            "multi_agent.workers.iv_history_worker.datetime",
            _make_datetime_mock(fake_now),
        )

        async def _stop():
            await asyncio.sleep(0.05)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=2.0),
            _stop(),
        )

        client.get_options_chain.assert_not_called()
        repo.write_snapshot.assert_not_called()
