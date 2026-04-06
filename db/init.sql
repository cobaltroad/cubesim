CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS cards (
    id               UUID        PRIMARY KEY,
    name             TEXT        NOT NULL,
    set_code         TEXT,
    collector_number TEXT,
    image_uri_small  TEXT,
    image_uri_normal TEXT,
    image_uri_large  TEXT,
    image_cached     BOOLEAN     NOT NULL DEFAULT FALSE,
    maindeck         BOOLEAN     NOT NULL DEFAULT TRUE,
    scryfall_data    JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS cards_name_idx    ON cards (name);
CREATE INDEX IF NOT EXISTS cards_set_idx     ON cards (set_code);
CREATE INDEX IF NOT EXISTS cards_cached_idx  ON cards (image_cached);
