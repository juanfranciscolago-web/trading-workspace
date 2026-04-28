"""
Unit tests for ATLAS core — orchestración de checks y construcción del mensaje.
~25 tests. Énfasis en fail-closed, size reduction, y todos los caminos de rejection.
No DB, no Redis — todo puro.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from multi_agent.communication.enums import AgentId, AtlasReason, ConsensusType, DecisionOutcome, RiskMode
from multi_agent.communication.schemas import AtlasValidationMessage, DecisionMessage, ConsensusState
from multi_agent.risk import atlas_validate
from multi_agent.risk.config import (
    BucketConfig,
    BucketDef,
    BuyingPowerLimits,
    ExposureLimits,
    GreekLimits,
    Phase1Limits,
    PnlLimits,
)
from multi_agent.risk.portfolio_snapshot import PortfolioSnapshot, PositionView, snapshot_hash

from ..agents.conftest import CapturingRepository
from multi_agent.agents import SCENARIOS, build_orchestrator


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pos(ticker, qty=100, price=440.0, vega=0.0) -> PositionView:
    return PositionView(
        ticker=ticker, asset_class="equity", strategy_type=None,
        market_value_usd=Decimal(str(abs(qty) * price)),
        quantity=qty, delta=Decimal(str(abs(qty))),
        vega=Decimal(str(vega)), theta=Decimal("0"),
    )


def _standard_limits() -> Phase1Limits:
    return Phase1Limits(
        phase=1,
        pnl=PnlLimits(
            daily_halt_pct=-2.5, weekly_halt_pct=-4.0,
            monthly_size_reduction_pct=-7.0,
            drawdown_halt_pct=-12.0, drawdown_kill_switch_pct=-25.0,
            daily_loss_kill_switch_pct=-8.0,
        ),
        exposure=ExposureLimits(
            single_name_max_pct=8.0, sector_max_pct=30.0, bucket_max_pct=45.0,
            beta_min=-0.3, beta_max=1.3,
        ),
        greeks=GreekLimits(vega_limit_pct_per_vix_point=3.0),
        buying_power=BuyingPowerLimits(normal_max_pct=40.0, macro_event_max_pct=25.0),
    )


def _standard_buckets() -> BucketConfig:
    return BucketConfig(buckets={
        "tech_mega_cap": BucketDef(description="Tech", tickers=("MSFT", "AAPL", "GOOGL")),
        "semis": BucketDef(description="Semis", tickers=("NVDA", "AMD")),
        "other": BucketDef(description="Other", tickers=()),
    })


def _healthy_snapshot() -> PortfolioSnapshot:
    positions = [
        _pos("MSFT", 100, 440.0),   # 4.4%
        _pos("NVDA", 50, 850.0),    # 4.25%
    ]
    ts = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
    sid = snapshot_hash(positions, Decimal("850000"), Decimal("0"), ts)
    return PortfolioSnapshot(
        positions=tuple(positions),
        nav_usd=Decimal("1000000"),
        cash_usd=Decimal("850000"),
        buying_power_used_pct=16.0,
        portfolio_beta=0.82,
        vega_total=-12400.0,
        pnl_daily_usd=Decimal("0"),
        pnl_daily_pct=0.0,
        pnl_weekly_pct=0.0,
        pnl_monthly_pct=0.0,
        drawdown_from_peak_pct=-2.1,
        snapshot_at=ts,
        snapshot_id=sid,
    )


def _run_cycle_and_validate(scenario_name="all_agree"):
    """Run a mock cycle and return (proposal, decision, snapshot)."""
    repo = CapturingRepository()
    orc = build_orchestrator(repo)
    result = orc.run_cycle(SCENARIOS[scenario_name])
    snapshot = _healthy_snapshot()
    limits = _standard_limits()
    buckets = _standard_buckets()
    atlas_msg = atlas_validate(result.proposal, result.decision, snapshot, limits, buckets)
    return result, atlas_msg


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAtlasCoreContract:
    def test_returns_atlas_validation_message(self):
        _, atlas_msg = _run_cycle_and_validate()
        assert isinstance(atlas_msg, AtlasValidationMessage)

    def test_message_has_atlas_agent_id(self):
        _, atlas_msg = _run_cycle_and_validate()
        assert atlas_msg.agent_id == AgentId.ATLAS

    def test_correlation_id_matches_proposal(self):
        result, atlas_msg = _run_cycle_and_validate()
        assert atlas_msg.correlation_id == result.proposal.correlation_id

    def test_parent_message_id_is_decision(self):
        result, atlas_msg = _run_cycle_and_validate()
        assert atlas_msg.parent_message_id == result.decision.message_id

    def test_atlas_version_set(self):
        _, atlas_msg = _run_cycle_and_validate()
        assert atlas_msg.atlas_version.startswith("atlas-")

    def test_evaluation_time_ms_positive(self):
        _, atlas_msg = _run_cycle_and_validate()
        assert atlas_msg.evaluation_time_ms >= 0

    def test_portfolio_snapshot_id_is_sha256(self):
        _, atlas_msg = _run_cycle_and_validate()
        assert len(atlas_msg.portfolio_snapshot_id) == 64

    def test_original_size_equals_proposed(self):
        result, atlas_msg = _run_cycle_and_validate()
        expected = Decimal(str(result.proposal.sizing.proposed_size_pct_portfolio))
        assert atlas_msg.original_size == expected


class TestApprovedTrade:
    def test_healthy_portfolio_trade_approved(self):
        _, atlas_msg = _run_cycle_and_validate("all_agree")
        assert atlas_msg.approved
        assert atlas_msg.executed_size > Decimal("0")

    def test_approved_reason_is_approved(self):
        _, atlas_msg = _run_cycle_and_validate("all_agree")
        assert atlas_msg.reason == AtlasReason.APPROVED

    def test_risk_mode_green_when_healthy(self):
        _, atlas_msg = _run_cycle_and_validate("all_agree")
        assert atlas_msg.risk_mode == RiskMode.GREEN

    def test_checks_passed_non_empty(self):
        _, atlas_msg = _run_cycle_and_validate("all_agree")
        assert len(atlas_msg.checks_passed) > 0

    def test_checks_failed_empty_when_approved(self):
        _, atlas_msg = _run_cycle_and_validate("all_agree")
        assert atlas_msg.checks_failed == []

    def test_stress_tests_in_metrics_snapshot(self):
        _, atlas_msg = _run_cycle_and_validate("all_agree")
        assert "stress.spx_down_5pct" in atlas_msg.metrics_snapshot
        assert "stress.vix_spike_30pct" in atlas_msg.metrics_snapshot


class TestKillSwitchRejection:
    def test_drawdown_kill_switch_rejects(self):
        repo = CapturingRepository()
        orc = build_orchestrator(repo)
        result = orc.run_cycle(SCENARIOS["all_agree"])

        # Snapshot with kill-switch-level drawdown
        ts = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
        positions = [_pos("MSFT", 100, 440.0)]
        sid = snapshot_hash(positions, Decimal("600000"), Decimal("-260000"), ts)
        bad_snapshot = PortfolioSnapshot(
            positions=tuple(positions),
            nav_usd=Decimal("1000000"),
            cash_usd=Decimal("600000"),
            buying_power_used_pct=20.0,
            portfolio_beta=0.82,
            vega_total=0.0,
            pnl_daily_usd=Decimal("-260000"),
            pnl_daily_pct=-26.0,
            pnl_weekly_pct=-26.0,
            pnl_monthly_pct=-26.0,
            drawdown_from_peak_pct=-26.0,
            snapshot_at=ts,
            snapshot_id=sid,
        )
        atlas_msg = atlas_validate(result.proposal, result.decision, bad_snapshot,
                                   _standard_limits(), _standard_buckets())
        assert not atlas_msg.approved
        assert atlas_msg.executed_size == Decimal("0")
        assert atlas_msg.reason == AtlasReason.REJECTED_KILL_SWITCH

    def test_daily_loss_kill_switch_rejects(self):
        repo = CapturingRepository()
        orc = build_orchestrator(repo)
        result = orc.run_cycle(SCENARIOS["all_agree"])

        ts = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
        positions = [_pos("MSFT", 100, 440.0)]
        sid = snapshot_hash(positions, Decimal("850000"), Decimal("-90000"), ts)
        bad_snapshot = PortfolioSnapshot(
            positions=tuple(positions),
            nav_usd=Decimal("1000000"), cash_usd=Decimal("850000"),
            buying_power_used_pct=15.0, portfolio_beta=0.82, vega_total=0.0,
            pnl_daily_usd=Decimal("-90000"), pnl_daily_pct=-9.0,
            pnl_weekly_pct=-9.0, pnl_monthly_pct=-9.0,
            drawdown_from_peak_pct=-9.0, snapshot_at=ts, snapshot_id=sid,
        )
        atlas_msg = atlas_validate(result.proposal, result.decision, bad_snapshot,
                                   _standard_limits(), _standard_buckets())
        assert not atlas_msg.approved
        assert atlas_msg.reason == AtlasReason.REJECTED_KILL_SWITCH


class TestFailClosed:
    def test_none_snapshot_triggers_fail_closed(self):
        """
        Simula que atlas_core crashea internamente pasando datos inválidos.
        ATLAS debe retornar reject, nunca propagar la excepción.
        """
        repo = CapturingRepository()
        orc = build_orchestrator(repo)
        result = orc.run_cycle(SCENARIOS["all_agree"])

        # Trigger exception by passing None — atlas_core should catch it
        class BrokenSnapshot:
            drawdown_from_peak_pct = -2.1
            pnl_daily_pct = 0.0
            pnl_weekly_pct = 0.0
            nav_usd = None   # will cause exception in checks
            snapshot_id = "broken"
            positions = ()
            buying_power_used_pct = 0.0
            portfolio_beta = 0.82
            vega_total = 0.0
            pnl_daily_usd = Decimal("0")

        atlas_msg = atlas_validate(result.proposal, result.decision, BrokenSnapshot(),  # type: ignore
                                   _standard_limits(), _standard_buckets())

        assert not atlas_msg.approved
        assert atlas_msg.executed_size == Decimal("0")
        assert atlas_msg.reason == AtlasReason.REJECTED_SYSTEM_ERROR

    def test_fail_closed_reason_is_system_error(self):
        from multi_agent.risk.atlas_core import _build_fail_closed
        repo = CapturingRepository()
        orc = build_orchestrator(repo)
        result = orc.run_cycle(SCENARIOS["all_agree"])
        snap = _healthy_snapshot()
        msg = _build_fail_closed(result.proposal, result.decision, snap, 99.9)
        assert msg.reason == AtlasReason.REJECTED_SYSTEM_ERROR
        assert not msg.approved
        assert msg.executed_size == Decimal("0")
        assert msg.evaluation_time_ms == 99.9


class TestRiskMode:
    def test_healthy_portfolio_is_green(self):
        _, atlas_msg = _run_cycle_and_validate()
        assert atlas_msg.risk_mode == RiskMode.GREEN

    def test_risk_mode_in_metrics_snapshot(self):
        _, atlas_msg = _run_cycle_and_validate()
        assert "portfolio.risk_mode" in atlas_msg.metrics_snapshot
