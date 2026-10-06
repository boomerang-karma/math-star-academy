-- Default sales territories. Idempotent: safe to re-run on every deploy.
-- Edit freely; leads are (re)assigned by HQ country on the next scoring run.

INSERT INTO sales.territory (name, countries, description) VALUES
    ('North America', ARRAY['US', 'CA'], 'United States and Canada'),
    ('EMEA', ARRAY['GB', 'IE', 'DE', 'FR', 'NL', 'BE', 'ES', 'IT', 'SE', 'NO', 'DK', 'FI',
                   'CH', 'AT', 'PL', 'PT', 'AE', 'IL', 'ZA'], 'Europe, Middle East and Africa'),
    ('APAC', ARRAY['AU', 'NZ', 'SG', 'IN', 'JP', 'KR', 'HK'], 'Asia Pacific'),
    ('LATAM', ARRAY['BR', 'MX', 'AR', 'CL', 'CO'], 'Latin America')
ON CONFLICT (name) DO UPDATE
    SET countries = EXCLUDED.countries,
        description = EXCLUDED.description;
