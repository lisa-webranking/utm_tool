-- UTM Governance Tool — PostgreSQL schema
-- Run once against the Cloud SQL instance to initialize tables.

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    email_hash    VARCHAR(64) UNIQUE NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS credentials (
    user_id       INT REFERENCES users(id) ON DELETE CASCADE,
    provider      VARCHAR(32) DEFAULT 'google',
    token_json    TEXT NOT NULL,
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, provider)
);

CREATE TABLE IF NOT EXISTS api_keys (
    user_id       INT REFERENCES users(id) ON DELETE CASCADE,
    service       VARCHAR(32) DEFAULT 'gemini',
    encrypted_key TEXT NOT NULL,
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, service)
);

CREATE TABLE IF NOT EXISTS client_configs (
    client_id     VARCHAR(128) PRIMARY KEY,
    version       INT NOT NULL DEFAULT 1,
    config_json   JSONB NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS utm_history (
    id                  SERIAL PRIMARY KEY,
    user_email_hash     VARCHAR(64) NOT NULL,
    user_email          VARCHAR(255) DEFAULT '',
    client_id           VARCHAR(128),
    property_id         VARCHAR(64),
    property_name       VARCHAR(255) DEFAULT '',
    final_url           TEXT NOT NULL,
    utm_source          VARCHAR(255),
    utm_medium          VARCHAR(255),
    utm_campaign        VARCHAR(512),
    campaign_name       VARCHAR(255) DEFAULT '',
    live_date           VARCHAR(32) DEFAULT '',
    expected_channel    VARCHAR(128) DEFAULT '',
    tracking_status     VARCHAR(32) DEFAULT 'pending',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_utm_history_user ON utm_history(user_email_hash);
CREATE INDEX IF NOT EXISTS idx_utm_history_client ON utm_history(client_id);
CREATE INDEX IF NOT EXISTS idx_utm_history_url ON utm_history(user_email_hash, property_id, final_url);
