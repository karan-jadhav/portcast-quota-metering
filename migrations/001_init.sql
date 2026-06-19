BEGIN;

CREATE TABLE quota_limits (
    org_id UUID NOT NULL,
    feature TEXT NOT NULL,

    limit_units INTEGER NOT NULL CHECK (limit_units >= 0),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (org_id, feature)
);

CREATE TABLE quota_counters (
    org_id UUID NOT NULL,
    feature TEXT NOT NULL,

    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,

    limit_units INTEGER NOT NULL CHECK (limit_units >= 0),
    used_units INTEGER NOT NULL DEFAULT 0 CHECK (used_units >= 0),
    reserved_units INTEGER NOT NULL DEFAULT 0 CHECK (reserved_units >= 0),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (org_id, feature, period_start),

    CHECK (period_end > period_start),
    CHECK (used_units + reserved_units <= limit_units),

    FOREIGN KEY (org_id, feature)
        REFERENCES quota_limits (org_id, feature)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE TABLE quota_reservations (
    reservation_id UUID PRIMARY KEY DEFAULT uuidv7(),

    org_id UUID NOT NULL,
    feature TEXT NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,

    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) > 0),
    units INTEGER NOT NULL CHECK (units > 0),

    status TEXT NOT NULL CHECK (
        status IN ('reserved', 'committed', 'released', 'expired')
    ),

    expires_at TIMESTAMPTZ NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (org_id, feature, period_start, idempotency_key),

    FOREIGN KEY (org_id, feature, period_start)
        REFERENCES quota_counters (org_id, feature, period_start)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX idx_quota_reservations_expiry
ON quota_reservations (expires_at)
WHERE status = 'reserved';

CREATE INDEX idx_quota_reservations_counter
ON quota_reservations (org_id, feature, period_start);

COMMIT;