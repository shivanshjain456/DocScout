-- DocScout 0009: analyst identity, subscriptions, digests, and OCR cache.
--
-- Implements Auth0 analyst profiles, persistent research interests, Brevo
-- regulatory digest subscriptions, delivery logging with deduplication,
-- and OCR.Space extraction caching.

SET search_path = public;

-- ---------------------------------------------------------------------------------------
-- users — analyst identity authenticated via Auth0 (OAuth 2.0 / OIDC).
-- ---------------------------------------------------------------------------------------
CREATE TABLE users (
    user_id      uuid        PRIMARY KEY DEFAULT uuidv7(),
    auth0_sub    text        NOT NULL,
    email        text        NOT NULL,
    display_name text,
    role         text        NOT NULL DEFAULT 'reader',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT uq_users_auth0_sub UNIQUE (auth0_sub),
    CONSTRAINT ck_users_role CHECK (role IN ('reader', 'admin'))
);

COMMENT ON TABLE users IS 'Analyst identities authenticated via Auth0 OIDC.';
COMMENT ON COLUMN users.auth0_sub IS 'Stable unique subject identifier from validated JWT (e.g. auth0|... or google-oauth2|...).';
COMMENT ON COLUMN users.role IS 'reader (analyst research) | admin (corpus management, ingestion, invalidation).';

-- ---------------------------------------------------------------------------------------
-- user_interests — saved regulatory research interests / watchlists.
-- ---------------------------------------------------------------------------------------
CREATE TABLE user_interests (
    interest_id uuid        PRIMARY KEY DEFAULT uuidv7(),
    user_id     uuid        NOT NULL,
    topic       text        NOT NULL,
    regulator   text        NOT NULL DEFAULT 'ALL',
    keywords    text[]      NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fk_interests_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT ck_interests_regulator CHECK (regulator IN ('RBI', 'SEBI', 'ALL')),
    CONSTRAINT uq_user_interest UNIQUE (user_id, topic, regulator)
);

CREATE INDEX idx_user_interests_user ON user_interests (user_id);
COMMENT ON TABLE user_interests IS 'Saved analyst research interests for personalized monitoring.';

-- ---------------------------------------------------------------------------------------
-- subscriptions — digest subscriptions with explicit consent and unsubscribe token.
-- ---------------------------------------------------------------------------------------
CREATE TABLE subscriptions (
    subscription_id   uuid        PRIMARY KEY DEFAULT uuidv7(),
    user_id           uuid        NOT NULL,
    email             text        NOT NULL,
    frequency         text        NOT NULL DEFAULT 'weekly',
    is_active         boolean     NOT NULL DEFAULT true,
    consent_ts        timestamptz NOT NULL DEFAULT now(),
    consent_ip        text,
    unsubscribe_token text        NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fk_subscriptions_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT uq_user_subscription UNIQUE (user_id),
    CONSTRAINT uq_subscriptions_token UNIQUE (unsubscribe_token),
    CONSTRAINT ck_subscriptions_frequency CHECK (frequency IN ('immediate', 'daily', 'weekly'))
);

CREATE INDEX idx_subscriptions_active ON subscriptions (is_active) WHERE is_active = true;
COMMENT ON TABLE subscriptions IS 'Topic-based digest subscriptions with explicit consent tracking.';

-- ---------------------------------------------------------------------------------------
-- subscription_topics — selected regulatory topics per subscription.
-- ---------------------------------------------------------------------------------------
CREATE TABLE subscription_topics (
    id              uuid        PRIMARY KEY DEFAULT uuidv7(),
    subscription_id uuid        NOT NULL,
    topic           text        NOT NULL,
    regulator       text        NOT NULL DEFAULT 'ALL',
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fk_sub_topics_subscription FOREIGN KEY (subscription_id)
        REFERENCES subscriptions (subscription_id) ON DELETE CASCADE,
    CONSTRAINT ck_sub_topics_regulator CHECK (regulator IN ('RBI', 'SEBI', 'ALL')),
    CONSTRAINT uq_subscription_topic UNIQUE (subscription_id, topic, regulator)
);

CREATE INDEX idx_subscription_topics_sub ON subscription_topics (subscription_id);

-- ---------------------------------------------------------------------------------------
-- digest_deliveries — durable email delivery log with Brevo provider tracking.
-- ---------------------------------------------------------------------------------------
CREATE TABLE digest_deliveries (
    delivery_id      uuid        PRIMARY KEY DEFAULT uuidv7(),
    subscription_id  uuid        NOT NULL,
    document_id      uuid        NOT NULL,
    version_id       uuid        NOT NULL,
    recipient_email  text        NOT NULL,
    brevo_message_id text,
    status           text        NOT NULL DEFAULT 'QUEUED',
    attempts         integer     NOT NULL DEFAULT 0,
    error_message    text,
    sent_at          timestamptz,
    delivered_at     timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fk_deliveries_subscription FOREIGN KEY (subscription_id)
        REFERENCES subscriptions (subscription_id) ON DELETE CASCADE,
    CONSTRAINT fk_deliveries_document FOREIGN KEY (document_id)
        REFERENCES documents (document_id) ON DELETE RESTRICT,
    CONSTRAINT fk_deliveries_version FOREIGN KEY (version_id)
        REFERENCES document_versions (version_id) ON DELETE RESTRICT,
    CONSTRAINT ck_deliveries_status CHECK (
        status IN ('QUEUED', 'SENDING', 'SENT', 'DELIVERED', 'FAILED', 'BOUNCED', 'SUPPRESSED')
    ),
    -- Deduplication invariant: a subscription never receives duplicate notification for the same document version
    CONSTRAINT uq_digest_delivery_version UNIQUE (subscription_id, version_id)
);

CREATE INDEX idx_digest_deliveries_status ON digest_deliveries (status);
CREATE INDEX idx_digest_deliveries_recipient ON digest_deliveries (recipient_email);
COMMENT ON TABLE digest_deliveries IS 'Durable email delivery log preventing duplicate sends on retries and restarts.';

-- ---------------------------------------------------------------------------------------
-- ocr_extractions — bounded OCR.Space extraction cache keyed by document content SHA-256.
-- ---------------------------------------------------------------------------------------
CREATE TABLE ocr_extractions (
    sha256          char(64)         PRIMARY KEY,
    provider        text             NOT NULL DEFAULT 'ocr.space',
    engine          text             NOT NULL DEFAULT 'engine2',
    status          text             NOT NULL,
    pages_processed integer          NOT NULL DEFAULT 0,
    extracted_text  text,
    error_detail    text,
    latency_ms      double precision,
    created_at      timestamptz      NOT NULL DEFAULT now(),

    CONSTRAINT ck_ocr_status CHECK (status IN ('SUCCESS', 'ERROR', 'ELIGIBILITY_EXCEEDED'))
);

COMMENT ON TABLE ocr_extractions IS 'Bounded OCR cache indexed by content hash sha256(pdf_bytes).';

-- ---------------------------------------------------------------------------------------
-- Least-privilege permissions for docscout_app
-- ---------------------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE ON users               TO docscout_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_interests      TO docscout_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON subscriptions       TO docscout_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON subscription_topics TO docscout_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON digest_deliveries   TO docscout_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ocr_extractions     TO docscout_app;
