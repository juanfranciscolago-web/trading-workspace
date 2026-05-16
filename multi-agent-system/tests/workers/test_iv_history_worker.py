"""Unit tests for IvHistoryWorker (S.6.iv-c).

All tests inject schwab_client + repo mocks. Worker construction with
missing schwab_client raises TypeError (Opción C — tests safe by default,
no path to real GCP).

asyncio_mode = "auto" en pyproject — async def tests run sin
@pytest.mark.asyncio decorator.
"""
from __future__ import annotations

import asyncio
import logging
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
    surface_repo: MagicMock | None = None,
    poll_interval_s: float = 0.05,
) -> tuple[IvHistoryWorker, MagicMock, MagicMock, MagicMock | None]:
    """Build IvHistoryWorker with mock repo + schwab_client.

    Returns (worker, mock_repo, mock_client, mock_surface_repo) for tests
    to configure. surface_repo defaults to None (Optional per ADR-006 D-α);
    tests verifying D3-1 isolation pass MagicMock() explicitly.
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
        surface_repo=surface_repo,
        poll_interval_s=poll_interval_s,
    )
    return worker, mock_repo, mock_client, surface_repo


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
        worker, _, _, _ = _make_worker()
        monkeypatch.setattr(
            "multi_agent.workers.iv_history_worker.datetime",
            _make_datetime_mock(fake_now),
        )
        assert worker._should_snapshot_now() is False

    def test_returns_false_on_sunday(self, monkeypatch):
        fake_now = datetime(2026, 5, 17, 22, 0, tzinfo=timezone.utc)
        worker, _, _, _ = _make_worker()
        monkeypatch.setattr(
            "multi_agent.workers.iv_history_worker.datetime",
            _make_datetime_mock(fake_now),
        )
        assert worker._should_snapshot_now() is False

    def test_returns_false_before_21_15_utc(self, monkeypatch):
        # Thursday 20:00 UTC (before snapshot time)
        fake_now = datetime(2026, 5, 14, 20, 0, tzinfo=timezone.utc)
        worker, _, _, _ = _make_worker()
        monkeypatch.setattr(
            "multi_agent.workers.iv_history_worker.datetime",
            _make_datetime_mock(fake_now),
        )
        assert worker._should_snapshot_now() is False

    def test_returns_true_after_21_15_no_snapshot_today(self, monkeypatch):
        # Thursday 22:00 UTC, canary SPY not yet snapshotted
        fake_now = datetime(2026, 5, 14, 22, 0, tzinfo=timezone.utc)
        worker, repo, _, _ = _make_worker(has_snapshot=False)
        monkeypatch.setattr(
            "multi_agent.workers.iv_history_worker.datetime",
            _make_datetime_mock(fake_now),
        )
        assert worker._should_snapshot_now() is True
        repo.has_snapshot_today.assert_called_once_with("SPY", date(2026, 5, 14))

    def test_returns_false_when_canary_already_snapshotted(self, monkeypatch):
        fake_now = datetime(2026, 5, 14, 22, 0, tzinfo=timezone.utc)
        worker, _, _, _ = _make_worker(has_snapshot=True)
        monkeypatch.setattr(
            "multi_agent.workers.iv_history_worker.datetime",
            _make_datetime_mock(fake_now),
        )
        assert worker._should_snapshot_now() is False


# ── TestSnapshotOneTicker ────────────────────────────────────────────────────

class TestSnapshotOneTicker:
    """_snapshot_one_ticker — single-ticker fetch + persist flow."""

    def test_writes_snapshot_when_chain_valid(self):
        worker, repo, client, _ = _make_worker()
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
        worker, repo, _, _ = _make_worker(chain_response=empty_chain)
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
        worker, repo, _, _ = _make_worker(chain_response=zero_chain)
        ts = datetime(2026, 5, 14, 21, 15, tzinfo=timezone.utc)

        worker._snapshot_one_ticker("SPY", ts)

        repo.write_snapshot.assert_not_called()


# ── TestSurfaceExtension ─────────────────────────────────────────────────────

class TestSurfaceExtension:
    """surface_repo extension on _snapshot_one_ticker — ADR-006 S.7.surf-c.

    Validates D3-1 isolation contract: iv_surface write failure NOT blocking
    iv_history write success. caplog pattern mirrors S.6.iv-d TestIvRankProgressive.
    """

    _LOGGER_NAME = "multi_agent.workers.iv_history_worker"

    def test_calls_surface_repo_write_chain_after_iv_history(self):
        """Happy path: surface_repo.write_chain_snapshot called after iv_history write."""
        mock_surface = MagicMock()
        mock_surface.write_chain_snapshot.return_value = 12  # 12 rows inserted
        worker, mock_repo, _, _ = _make_worker(surface_repo=mock_surface)
        ts = datetime(2026, 5, 16, 21, 15, tzinfo=timezone.utc)

        worker._snapshot_one_ticker("SPY", ts)

        # iv_history write happened
        mock_repo.write_snapshot.assert_called_once()
        # iv_surface write happened
        mock_surface.write_chain_snapshot.assert_called_once()

    def test_surface_repo_none_does_not_call_surface_write(self):
        """D-α: surface_repo=None default → skip surface call entirely."""
        worker, mock_repo, _, surface_repo = _make_worker(surface_repo=None)
        ts = datetime(2026, 5, 16, 21, 15, tzinfo=timezone.utc)

        worker._snapshot_one_ticker("SPY", ts)

        # iv_history still writes
        mock_repo.write_snapshot.assert_called_once()
        # surface_repo is None → no call possible
        assert surface_repo is None

    def test_surface_write_failure_does_not_block_iv_history_success(self):
        """D3-1: surface raises → iv_history write still succeeds, no re-raise."""
        mock_surface = MagicMock()
        mock_surface.write_chain_snapshot.side_effect = RuntimeError("DB connection lost")
        worker, mock_repo, _, _ = _make_worker(surface_repo=mock_surface)
        ts = datetime(2026, 5, 16, 21, 15, tzinfo=timezone.utc)

        # Should NOT raise — surface failure isolated
        worker._snapshot_one_ticker("SPY", ts)

        # iv_history write still happened (BEFORE surface attempt)
        mock_repo.write_snapshot.assert_called_once()
        # surface attempt was made
        mock_surface.write_chain_snapshot.assert_called_once()

    def test_surface_failure_logs_warning_with_exc_info(self, caplog):
        """D-δ: failure logs WARNING with 'D3-1 isolation' marker + exc_info."""
        mock_surface = MagicMock()
        mock_surface.write_chain_snapshot.side_effect = RuntimeError("simulated DB error")
        worker, _, _, _ = _make_worker(surface_repo=mock_surface)
        ts = datetime(2026, 5, 16, 21, 15, tzinfo=timezone.utc)

        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            worker._snapshot_one_ticker("SPY", ts)

        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and r.name == self._LOGGER_NAME
        ]
        assert any(
            "iv_surface write failed" in r.message and "D3-1 isolation" in r.message
            for r in warnings
        )
        assert any(r.exc_info is not None for r in warnings)

    def test_surface_called_with_correct_chain_ticker_ts(self):
        """Args validation: write_chain_snapshot(chain, ticker, ts) — positional."""
        mock_surface = MagicMock()
        mock_surface.write_chain_snapshot.return_value = 5
        worker, _, _, _ = _make_worker(surface_repo=mock_surface)
        ts = datetime(2026, 5, 16, 21, 15, tzinfo=timezone.utc)

        worker._snapshot_one_ticker("SPY", ts)

        # Verify positional args (chain, ticker, ts)
        call_args = mock_surface.write_chain_snapshot.call_args
        chain_arg, ticker_arg, ts_arg = call_args[0]  # positional
        assert chain_arg == _SAMPLE_CHAIN  # default fixture
        assert ticker_arg == "SPY"
        assert ts_arg == ts


# ── TestSnapshotAllTickers ───────────────────────────────────────────────────

class TestSnapshotAllTickers:
    """_snapshot_all_tickers — per-ticker error isolation (D-γ)."""

    async def test_per_ticker_failure_does_not_block_others(self):
        # Mock get_options_chain to raise for "NVDA" only; succeed for others.
        worker, repo, client, _ = _make_worker()

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
        worker, _, _, _ = _make_worker(poll_interval_s=10.0)

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
        worker, repo, client, _ = _make_worker(poll_interval_s=10.0)
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
