-- V014: Add cache_creation_input_tokens to analytics.llm_costs.
--
-- cache_creation (writing to Anthropic prompt cache) costs MORE than base input:
--   5-min TTL: 1.25x input_rate
--   1-hr TTL:  2.00x input_rate
-- Tracked separately from cached_input_tokens (reads: 0.10x input, 90% cheaper).
-- Omitting this column causes cost underestimation when agents use prompt caching.
--
-- Existing rows get DEFAULT 0 (no cache creation before this migration).

ALTER TABLE analytics.llm_costs
    ADD COLUMN IF NOT EXISTS cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN analytics.llm_costs.cache_creation_input_tokens IS
    'Tokens used to write to Anthropic prompt cache (creation). '
    'Priced at 5-min TTL rate by default (1.25x input_per_million). '
    'Distinct from cached_input_tokens which tracks cache reads (0.10x input).';
