"""
Tests for multi-agent communication schemas.
Covers: round-trip JSON serialization, field validation, and factory dispatch.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from multi_agent.communication import (
    AgentId,
    AtlasDecision,
    AtlasValidationMessage,
    CalibrationUpdate,
    ConsensusState,
    ConsensusType,
    CritiqueArgument,
    CritiqueMessage,
    DataSignature,
    DecisionMessage,
    DecisionOutcome,
    DissentEvaluation,
    EvidenceItem,
    ExecutionMessage,
    FillRecord,
    LimitDistances,
    MessageType,
    OptionLeg,
    OptionType,
    PortfolioImpact,
    PortfolioState,
    PostmortemMessage,
    ProposalMessage,
    RiskMode,
    SizeModulation,
    SlippageInfo,
    Stance,
    StressTestResult,
    StrategyType,
    Thesis,
    ThesisEvaluation,
    TradeDetails,
    TradeOutcome,
    TradeResult,
    TradeSizing,
    TradeStatus,
    TradeStructure,
    deserialize_message,
)
from multi_agent.communication.enums import AssetClass, Direction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CORR_ID = uuid4()


@pytest.fixture
def proposal_data() -> dict:
    return {
        "message_type": "PROPOSAL",
        "agent_id": "ATHENA",
        "correlation_id": str(CORR_ID),
        "trade": {
            "ticker": "MSFT",
            "asset_class": "option",
            "strategy_type": "CSP",
            "structure": {
                "legs": [
                    {
                        "action": "sell",
                        "instrument_type": "put",
                        "strike": "410",
                        "expiration": "2026-06-19",
                        "quantity": 10,
                    }
                ],
                "estimated_credit": "4.85",
                "max_profit": "4850",
                "max_loss": "405150",
                "breakeven": "405.15",
                "buying_power_required": "41000",
            },
        },
        "thesis": {
            "premise": "MSFT en zona de soporte técnico con IV Rank elevado post-earnings",
            "mechanism": "IV crush post-earnings + soporte horizontal + delta 0.18 = POP 78%",
            "key_data_points": [
                "IV Rank: 62 (percentil 78 últimos 12 meses)",
                "Soporte 408-412 testeado 4 veces últimos 90 días",
            ],
            "invalidation": "Cierre diario debajo de 405 con volumen >150% promedio",
            "target": "50% max profit ($2,425)",
            "time_horizon_days": 45,
            "expected_holding_period_days": 22,
        },
        "conviction_score": 78,
        "sizing": {
            "proposed_size_pct_portfolio": 4.1,
            "proposed_size_usd": "41000",
            "kelly_suggested": 5.2,
            "kelly_fraction_applied": 0.25,
        },
        "self_acknowledged_biases": ["Mi modelo no captura riesgo de tail event geopolítico"],
        "data_signature": {
            "data_sources": ["schwab_options_chain", "internal_backtester"],
            "data_timestamp": "2026-04-28T14:30:00Z",
            "model_version": "athena-csp-v2.3",
        },
    }


@pytest.fixture
def critique_data() -> dict:
    return {
        "message_type": "CRITIQUE",
        "agent_id": "NYX",
        "correlation_id": str(CORR_ID),
        "parent_message_id": str(uuid4()),
        "stance": "DISAGREE",
        "argument": {
            "summary": "Setup estadísticamente válido pero contexto narrativo extremo",
            "evidence": [
                {
                    "claim": "Sentiment retail tech está en percentil 91 últimos 5 años",
                    "data_source": "AAII tech allocation survey",
                    "value": 91,
                },
                {
                    "claim": "VIX está en 11.2",
                    "data_source": "vix_realtime",
                    "value": 11.2,
                },
            ],
            "concern": "Vendiendo volatilidad cuando vol ya está en mínimos",
            "data_that_would_change_my_mind": "Si IV Rank > 75 o VIX sube > 15",
        },
        "veto_request": False,
        "contrarian_flag_raised": True,
    }


@pytest.fixture
def decision_data() -> dict:
    return {
        "message_type": "DECISION",
        "agent_id": "ATLAS",
        "correlation_id": str(CORR_ID),
        "outcome": "APPROVED_WITH_CONDITIONS",
        "consensus_state": {
            "agree": ["ATHENA", "APOLLO"],
            "disagree": ["NYX"],
            "neutral": ["HERMES", "VESTA"],
            "consensus_type": "MAJORITY_WITH_PRODUCTIVE_DISAGREEMENT",
        },
        "size_modulation": {
            "original_size_pct": 4.1,
            "approved_size_pct": 2.05,
            "reduction_reason": "NYX disagreement con argumento estructural válido — size 50%",
        },
        "conditions": [
            "Watch flag activo: si VIX < 10 antes de entrada, NYX puede bloquear",
            "Stop ajustado: cierre si MSFT toca 403",
        ],
    }


@pytest.fixture
def atlas_validation_data() -> dict:
    return {
        "message_type": "ATLAS_VALIDATION",
        "agent_id": "ATLAS",
        "correlation_id": str(CORR_ID),
        "decision": "APPROVED_WITH_CONDITIONS",
        "portfolio_impact": {
            "current_state": {
                "portfolio_beta": 0.87,
                "tech_concentration_pct": 28.4,
                "vega_total": -1240.0,
                "drawdown_from_peak_pct": 2.1,
                "buying_power_used_pct": 34.0,
            },
            "post_trade_state": {
                "portfolio_beta": 0.91,
                "tech_concentration_pct": 30.5,
                "vega_total": -1380.0,
                "drawdown_from_peak_pct": 2.1,
                "buying_power_used_pct": 38.0,
            },
            "limit_distances": {
                "tech_concentration_limit": 35.0,
                "distance_to_limit_pct": 13.0,
                "vega_limit": -2000.0,
                "distance_to_vega_limit_pct": 31.0,
            },
        },
        "stress_test_results": [
            {"scenario": "SPX_-5pct", "projected_pl_usd": -8200.0, "projected_pl_pct": -0.82},
            {"scenario": "VIX_to_30", "projected_pl_usd": -4500.0, "projected_pl_pct": -0.45},
        ],
        "modulations_applied": ["Size aprobado al 2.05% según Decision previa"],
        "risk_mode": "GREEN",
    }


@pytest.fixture
def execution_data() -> dict:
    return {
        "message_type": "EXECUTION",
        "agent_id": "HERMES",
        "correlation_id": str(CORR_ID),
        "execution_status": "filled",
        "fills": [
            {
                "leg": 1,
                "fill_price": "4.82",
                "fill_quantity": 10,
                "fill_timestamp": "2026-04-28T14:35:42.821Z",
                "venue": "SCHWAB",
            }
        ],
        "slippage_vs_proposal": {
            "expected_credit": "4.85",
            "actual_credit": "4.82",
            "slippage_pct": -0.62,
        },
        "execution_time_ms": 3421,
    }


@pytest.fixture
def postmortem_data() -> dict:
    return {
        "message_type": "POSTMORTEM",
        "agent_id": "ATHENA",
        "correlation_id": str(CORR_ID),
        "trade_owner": "ATHENA",
        "outcome": {
            "result": "WIN",
            "pl_usd": 2410.0,
            "pl_pct_portfolio": 0.24,
            "holding_period_days": 19,
            "exit_reason": "50% max profit hit",
        },
        "thesis_evaluation": {
            "premise_validated": True,
            "mechanism_worked_as_expected": True,
            "invalidation_triggered": False,
            "lessons": ["IV crush ocurrió como modelo predijo"],
        },
        "dissent_evaluation": [
            {
                "dissenting_agent": "NYX",
                "dissent_validated": False,
                "validation_reasoning": "VIX se mantuvo bajo pero sentiment no se materializó",
                "trust_score_adjustment": -0.02,
            }
        ],
        "calibration_update": {
            "predicted_pop": 78,
            "actual_outcome": "WIN",
            "brier_score_contribution": 0.048,
        },
    }


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


class TestProposalRoundTrip:
    def test_creates_from_dict(self, proposal_data):
        msg = ProposalMessage.model_validate(proposal_data)
        assert msg.message_type == MessageType.PROPOSAL
        assert msg.agent_id == AgentId.ATHENA
        assert msg.conviction_score == 78
        assert msg.trade.ticker == "MSFT"
        assert msg.trade.strategy_type == StrategyType.CSP
        assert msg.sizing.kelly_fraction_applied == 0.25

    def test_json_round_trip(self, proposal_data):
        msg = ProposalMessage.model_validate(proposal_data)
        serialized = json.loads(msg.model_dump_json())
        restored = ProposalMessage.model_validate(serialized)
        assert restored.message_id == msg.message_id
        assert restored.conviction_score == msg.conviction_score
        assert restored.trade.ticker == msg.trade.ticker

    def test_auto_generates_message_id(self, proposal_data):
        a = ProposalMessage.model_validate(proposal_data)
        b = ProposalMessage.model_validate(proposal_data)
        assert a.message_id != b.message_id

    def test_correlation_id_preserved(self, proposal_data):
        msg = ProposalMessage.model_validate(proposal_data)
        assert msg.correlation_id == CORR_ID

    def test_immutable(self, proposal_data):
        msg = ProposalMessage.model_validate(proposal_data)
        with pytest.raises(ValidationError):
            msg.conviction_score = 99  # type: ignore[misc]

    def test_schema_version_default(self, proposal_data):
        msg = ProposalMessage.model_validate(proposal_data)
        assert msg.schema_version == "1.0"


class TestCritiqueRoundTrip:
    def test_creates_from_dict(self, critique_data):
        msg = CritiqueMessage.model_validate(critique_data)
        assert msg.message_type == MessageType.CRITIQUE
        assert msg.stance == Stance.DISAGREE
        assert msg.contrarian_flag_raised is True
        assert len(msg.argument.evidence) == 2

    def test_json_round_trip(self, critique_data):
        msg = CritiqueMessage.model_validate(critique_data)
        serialized = json.loads(msg.model_dump_json())
        restored = CritiqueMessage.model_validate(serialized)
        assert restored.stance == msg.stance
        assert restored.argument.summary == msg.argument.summary


class TestDecisionRoundTrip:
    def test_creates_from_dict(self, decision_data):
        msg = DecisionMessage.model_validate(decision_data)
        assert msg.message_type == MessageType.DECISION
        assert msg.outcome == DecisionOutcome.APPROVED_WITH_CONDITIONS
        assert len(msg.consensus_state.agree) == 2
        assert len(msg.conditions) == 2
        assert msg.size_modulation.approved_size_pct == 2.05

    def test_json_round_trip(self, decision_data):
        msg = DecisionMessage.model_validate(decision_data)
        serialized = json.loads(msg.model_dump_json())
        restored = DecisionMessage.model_validate(serialized)
        assert restored.outcome == msg.outcome
        assert restored.size_modulation.reduction_reason == msg.size_modulation.reduction_reason

    def test_atlas_validation_defaults_pending(self, decision_data):
        msg = DecisionMessage.model_validate(decision_data)
        assert msg.atlas_validation.status == "PENDING"


class TestAtlasValidationRoundTrip:
    def test_creates_from_dict(self, atlas_validation_data):
        msg = AtlasValidationMessage.model_validate(atlas_validation_data)
        assert msg.message_type == MessageType.ATLAS_VALIDATION
        assert msg.decision == AtlasDecision.APPROVED_WITH_CONDITIONS
        assert msg.risk_mode == RiskMode.GREEN
        assert len(msg.stress_test_results) == 2

    def test_json_round_trip(self, atlas_validation_data):
        msg = AtlasValidationMessage.model_validate(atlas_validation_data)
        serialized = json.loads(msg.model_dump_json())
        restored = AtlasValidationMessage.model_validate(serialized)
        assert restored.risk_mode == msg.risk_mode
        assert restored.portfolio_impact.current_state.portfolio_beta == pytest.approx(0.87)


class TestExecutionRoundTrip:
    def test_creates_from_dict(self, execution_data):
        msg = ExecutionMessage.model_validate(execution_data)
        assert msg.message_type == MessageType.EXECUTION
        assert msg.execution_status == TradeStatus.FILLED
        assert msg.execution_time_ms == 3421

    def test_json_round_trip(self, execution_data):
        msg = ExecutionMessage.model_validate(execution_data)
        serialized = json.loads(msg.model_dump_json())
        restored = ExecutionMessage.model_validate(serialized)
        assert restored.execution_status == msg.execution_status
        assert restored.fills[0].venue == "SCHWAB"


class TestPostmortemRoundTrip:
    def test_creates_from_dict(self, postmortem_data):
        msg = PostmortemMessage.model_validate(postmortem_data)
        assert msg.message_type == MessageType.POSTMORTEM
        assert msg.outcome.result == TradeResult.WIN
        assert msg.calibration_update.predicted_pop == 78
        assert msg.dissent_evaluation[0].trust_score_adjustment == pytest.approx(-0.02)

    def test_json_round_trip(self, postmortem_data):
        msg = PostmortemMessage.model_validate(postmortem_data)
        serialized = json.loads(msg.model_dump_json())
        restored = PostmortemMessage.model_validate(serialized)
        assert restored.outcome.result == msg.outcome.result
        assert restored.trade_owner == msg.trade_owner


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestProposalValidation:
    def test_conviction_score_out_of_range(self, proposal_data):
        proposal_data["conviction_score"] = 101
        with pytest.raises(ValidationError):
            ProposalMessage.model_validate(proposal_data)

    def test_conviction_score_negative(self, proposal_data):
        proposal_data["conviction_score"] = -1
        with pytest.raises(ValidationError):
            ProposalMessage.model_validate(proposal_data)

    def test_kelly_fraction_above_one(self, proposal_data):
        proposal_data["sizing"]["kelly_fraction_applied"] = 1.5
        with pytest.raises(ValidationError):
            ProposalMessage.model_validate(proposal_data)

    def test_kelly_fraction_zero(self, proposal_data):
        proposal_data["sizing"]["kelly_fraction_applied"] = 0.0
        with pytest.raises(ValidationError):
            ProposalMessage.model_validate(proposal_data)

    def test_size_pct_above_100(self, proposal_data):
        proposal_data["sizing"]["proposed_size_pct_portfolio"] = 101.0
        with pytest.raises(ValidationError):
            ProposalMessage.model_validate(proposal_data)

    def test_empty_legs_rejected(self, proposal_data):
        proposal_data["trade"]["structure"]["legs"] = []
        with pytest.raises(ValidationError):
            ProposalMessage.model_validate(proposal_data)

    def test_empty_key_data_points_rejected(self, proposal_data):
        proposal_data["thesis"]["key_data_points"] = []
        with pytest.raises(ValidationError):
            ProposalMessage.model_validate(proposal_data)

    def test_wrong_message_type_rejected(self, proposal_data):
        proposal_data["message_type"] = "CRITIQUE"
        with pytest.raises(ValidationError):
            ProposalMessage.model_validate(proposal_data)

    def test_invalid_agent_id_rejected(self, proposal_data):
        proposal_data["agent_id"] = "ZEUS"
        with pytest.raises(ValidationError):
            ProposalMessage.model_validate(proposal_data)


class TestAtlasValidationValidation:
    def test_empty_stress_tests_rejected(self, atlas_validation_data):
        atlas_validation_data["stress_test_results"] = []
        with pytest.raises(ValidationError):
            AtlasValidationMessage.model_validate(atlas_validation_data)


class TestPostmortemValidation:
    def test_brier_score_above_one_rejected(self, postmortem_data):
        postmortem_data["calibration_update"]["brier_score_contribution"] = 1.5
        with pytest.raises(ValidationError):
            PostmortemMessage.model_validate(postmortem_data)

    def test_trust_score_out_of_range(self, postmortem_data):
        postmortem_data["dissent_evaluation"][0]["trust_score_adjustment"] = -2.0
        with pytest.raises(ValidationError):
            PostmortemMessage.model_validate(postmortem_data)

    def test_predicted_pop_above_100(self, postmortem_data):
        postmortem_data["calibration_update"]["predicted_pop"] = 101
        with pytest.raises(ValidationError):
            PostmortemMessage.model_validate(postmortem_data)


# ---------------------------------------------------------------------------
# Factory (deserialize_message) tests
# ---------------------------------------------------------------------------


class TestFactory:
    def test_dispatches_proposal(self, proposal_data):
        msg = deserialize_message(proposal_data)
        assert isinstance(msg, ProposalMessage)

    def test_dispatches_critique(self, critique_data):
        msg = deserialize_message(critique_data)
        assert isinstance(msg, CritiqueMessage)

    def test_dispatches_decision(self, decision_data):
        msg = deserialize_message(decision_data)
        assert isinstance(msg, DecisionMessage)

    def test_dispatches_atlas_validation(self, atlas_validation_data):
        msg = deserialize_message(atlas_validation_data)
        assert isinstance(msg, AtlasValidationMessage)

    def test_dispatches_execution(self, execution_data):
        msg = deserialize_message(execution_data)
        assert isinstance(msg, ExecutionMessage)

    def test_dispatches_postmortem(self, postmortem_data):
        msg = deserialize_message(postmortem_data)
        assert isinstance(msg, PostmortemMessage)

    def test_missing_message_type_raises(self):
        with pytest.raises(ValueError, match="Missing 'message_type'"):
            deserialize_message({"agent_id": "ATHENA"})

    def test_unknown_message_type_raises(self):
        with pytest.raises(ValueError, match="Unknown message_type"):
            deserialize_message({"message_type": "GHOST", "agent_id": "ATHENA"})

    def test_factory_round_trip_preserves_data(self, proposal_data):
        original = ProposalMessage.model_validate(proposal_data)
        raw = json.loads(original.model_dump_json())
        restored = deserialize_message(raw)
        assert isinstance(restored, ProposalMessage)
        assert restored.message_id == original.message_id
        assert restored.conviction_score == original.conviction_score
