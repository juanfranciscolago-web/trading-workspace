-- V001: PostgreSQL extensions, all schemas, and migration tracking table.
-- Idempotent: safe to re-run on an existing database.

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA IF NOT EXISTS shared;
CREATE SCHEMA IF NOT EXISTS agents;
CREATE SCHEMA IF NOT EXISTS messages;
CREATE SCHEMA IF NOT EXISTS trades;
CREATE SCHEMA IF NOT EXISTS portfolio;
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS analytics;

-- Migration tracking: migrate.py writes here; docker-entrypoint-initdb.d does not.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     VARCHAR(20)  PRIMARY KEY,
    filename    VARCHAR(200) NOT NULL,
    applied_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    checksum    VARCHAR(64)  NOT NULL
);
