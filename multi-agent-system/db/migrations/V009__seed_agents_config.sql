-- V009: Seed the 6 agents into agents.config and agents.state.
-- Idempotent via ON CONFLICT DO NOTHING.

INSERT INTO agents.config (
    agent_id, display_name, role,
    time_horizon_min_days, time_horizon_max_days,
    default_llm_model, max_portfolio_pct
) VALUES
    ('athena', 'ATHENA',
     'Cuantitativa sistemática (CSP, credit spreads, mean reversion)',
     15, 45, 'claude-sonnet-4-6', 20.0),
    ('apollo', 'APOLLO',
     'Macro discrecional (LEAPs, swing equity, crypto spot)',
     14, 180, 'claude-sonnet-4-6', 20.0),
    ('hermes', 'HERMES',
     'Tactical flow (0DTE, intraday, weeklies)',
     0, 7, 'claude-sonnet-4-6', 10.0),
    ('nyx', 'NYX',
     'Contrarian independiente (asimetría narrativa-realidad)',
     14, 84, 'claude-sonnet-4-6', 15.0),
    ('vesta', 'VESTA',
     'Rotación sectorial (cross-sectional, sub-industrias)',
     28, 182, 'claude-sonnet-4-6', 20.0),
    ('atlas', 'ATLAS',
     'Guardian del portfolio (riesgo, validación pre-execution)',
     0, 0, 'claude-sonnet-4-6', 0.0)
ON CONFLICT (agent_id) DO NOTHING;

INSERT INTO agents.state (agent_id)
SELECT agent_id FROM agents.config
ON CONFLICT (agent_id) DO NOTHING;
