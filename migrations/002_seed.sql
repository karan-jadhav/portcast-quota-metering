BEGIN;

WITH organizations (org_id, multiplier) AS (
    VALUES
        ('00000000-0000-0000-0000-000000000001'::uuid, 1.0),
        ('00000000-0000-0000-0000-000000000002'::uuid, 20.0),
        ('00000000-0000-0000-0000-000000000003'::uuid, 0.1),
        ('00000000-0000-0000-0000-000000000004'::uuid, 2.0),
        ('00000000-0000-0000-0000-000000000005'::uuid, 5.0),
        ('00000000-0000-0000-0000-000000000006'::uuid, 10.0),
        ('00000000-0000-0000-0000-000000000007'::uuid, 0.5),
        ('00000000-0000-0000-0000-000000000008'::uuid, 3.0),
        ('00000000-0000-0000-0000-000000000009'::uuid, 8.0),
        ('00000000-0000-0000-0000-000000000010'::uuid, 15.0)
),
features (feature, base_limit) AS (
    VALUES
        ('container-tracking', 500),
        ('sailing-schedule', 1000),
        ('shipment-events', 250),
        ('analytics-export', 100)
)
INSERT INTO quota_limits (org_id, feature, limit_units)
SELECT org_id, feature, (base_limit * multiplier)::integer
FROM organizations
CROSS JOIN features
ON CONFLICT (org_id, feature)
DO UPDATE SET
    limit_units = EXCLUDED.limit_units,
    updated_at = now();

COMMIT;
