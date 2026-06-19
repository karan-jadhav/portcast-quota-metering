BEGIN;

INSERT INTO quota_limits (org_id, feature, limit_units)
VALUES
    ('00000000-0000-0000-0000-000000000001', 'container-tracking', 500),
    ('00000000-0000-0000-0000-000000000001', 'sailing-schedule', 1000),

    ('00000000-0000-0000-0000-000000000002', 'container-tracking', 10000),
    ('00000000-0000-0000-0000-000000000002', 'sailing-schedule', 20000),

    ('00000000-0000-0000-0000-000000000003', 'container-tracking', 50),
    ('00000000-0000-0000-0000-000000000003', 'sailing-schedule', 100)
ON CONFLICT (org_id, feature)
DO UPDATE SET
    limit_units = EXCLUDED.limit_units,
    updated_at = now();

COMMIT;