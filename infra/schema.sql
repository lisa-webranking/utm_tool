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
    client_id           VARCHAR(128) PRIMARY KEY,
    version             INT NOT NULL DEFAULT 1,
    -- GA4 link
    ga4_property_id     VARCHAR(64) DEFAULT '',
    ga4_property_name   VARCHAR(255) DEFAULT '',
    ga4_client_name     VARCHAR(255) DEFAULT '',
    -- Defaults
    default_country     VARCHAR(8) DEFAULT '',
    expected_domain     VARCHAR(255) DEFAULT '',
    -- Allowed UTM values (PostgreSQL arrays, NOT JSON)
    sources             TEXT[] NOT NULL DEFAULT '{}',
    mediums             TEXT[] NOT NULL DEFAULT '{}',
    campaign_types      TEXT[] NOT NULL DEFAULT '{}',
    -- Campaign naming rules
    campaign_notes      TEXT[] NOT NULL DEFAULT '{}',
    campaign_examples   TEXT[] NOT NULL DEFAULT '{}',
    -- Shared link
    shared_link         TEXT DEFAULT '',
    shared_base_url     TEXT DEFAULT '',
    -- Upload tracking
    source_file_name    VARCHAR(255) DEFAULT '',
    source_file_sha256  VARCHAR(64) DEFAULT '',
    -- Audit
    updated_by          VARCHAR(255) DEFAULT '',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS client_medium_source_map (
    client_id   VARCHAR(128) REFERENCES client_configs(client_id) ON DELETE CASCADE,
    medium      VARCHAR(255) NOT NULL,
    source      VARCHAR(255) NOT NULL,
    PRIMARY KEY (client_id, medium, source)
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
CREATE UNIQUE INDEX IF NOT EXISTS idx_utm_history_url ON utm_history(user_email_hash, property_id, final_url);
