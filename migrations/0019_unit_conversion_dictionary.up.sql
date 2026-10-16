-- Migration 0019: Financial Unit Conversion Dictionary (FEAT-028)
-- Stores statutory financial units, scale multipliers, and search expansion aliases.

CREATE TABLE IF NOT EXISTS financial_unit_scales (
    id TEXT PRIMARY KEY,
    unit_symbol TEXT NOT NULL,
    canonical_unit TEXT NOT NULL,
    system_type TEXT NOT NULL DEFAULT 'INDIAN', -- 'INDIAN', 'INTERNATIONAL', 'PERCENTAGE', 'METRIC'
    scale_multiplier DOUBLE PRECISION NOT NULL,
    display_name TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_unit_scales_symbol ON financial_unit_scales(unit_symbol);
CREATE INDEX IF NOT EXISTS idx_unit_scales_canonical ON financial_unit_scales(canonical_unit);
CREATE INDEX IF NOT EXISTS idx_unit_scales_system ON financial_unit_scales(system_type);

-- Seed core regulatory financial scales
INSERT INTO financial_unit_scales (id, unit_symbol, canonical_unit, system_type, scale_multiplier, display_name, aliases)
VALUES
    ('scale-crore', 'Cr', 'INR', 'INDIAN', 10000000.0, 'Crore', '["crore", "crores", "cr", "crs", "koti"]'::jsonb),
    ('scale-lakh', 'Lakh', 'INR', 'INDIAN', 100000.0, 'Lakh', '["lakh", "lakhs", "lac", "lacs", "l"]'::jsonb),
    ('scale-thousand', 'k', 'INR', 'INDIAN', 1000.0, 'Thousand', '["thousand", "thousands", "k"]'::jsonb),
    ('scale-million', 'M', 'USD', 'INTERNATIONAL', 1000000.0, 'Million', '["million", "millions", "m", "mn"]'::jsonb),
    ('scale-billion', 'B', 'USD', 'INTERNATIONAL', 1000000000.0, 'Billion', '["billion", "billions", "b", "bn"]'::jsonb),
    ('scale-trillion', 'T', 'USD', 'INTERNATIONAL', 1000000000000.0, 'Trillion', '["trillion", "trillions", "t", "tn"]'::jsonb),
    ('scale-bps', 'bps', 'RATIO', 'PERCENTAGE', 0.0001, 'Basis Points', '["bps", "basis point", "basis points", "bp"]'::jsonb),
    ('scale-pct', '%', 'RATIO', 'PERCENTAGE', 0.01, 'Percent', '["%", "pct", "percent", "percentage"]'::jsonb)
ON CONFLICT (id) DO NOTHING;
