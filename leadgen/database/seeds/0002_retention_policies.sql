-- Retention schedule enforced nightly by the retention job (pipeline/handlers.py).
-- Keep in sync with the Record of Processing Activities in docs/COMPLIANCE.md.

INSERT INTO privacy.retention_policy (data_class, retain_days, action, description) VALUES
    ('raw_payload',       30,  'delete',    'Bronze-zone upstream responses (S3 lifecycle enforces the same window)'),
    ('web_event',        395,  'delete',    'First-party web events (13 months, matching analytics norms)'),
    ('signal',           365,  'delete',    'Intent and engagement signals'),
    ('person_unengaged', 180,  'delete',    'Scraped person records never linked to an engaged lead'),
    ('source_record',    730,  'delete',    'Normalized source records of organizations'),
    ('lead_disqualified', 365, 'anonymize', 'Disqualified leads keep firmographics, drop the person link')
ON CONFLICT (data_class) DO UPDATE
    SET retain_days = EXCLUDED.retain_days,
        action = EXCLUDED.action,
        description = EXCLUDED.description;
