-- Migration 0015: Document formulas table for FEAT-022

CREATE TABLE IF NOT EXISTS document_formulas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NULL,
    doc_id VARCHAR(255) NOT NULL,
    formula_name VARCHAR(255) NOT NULL,
    raw_expression TEXT NOT NULL,
    parsed_ast JSONB NOT NULL DEFAULT '{}'::jsonb,
    variables JSONB NOT NULL DEFAULT '{}'::jsonb,
    char_start INT NOT NULL DEFAULT 0,
    char_end INT NOT NULL DEFAULT 0,
    confidence FLOAT NOT NULL DEFAULT 1.0,
    standard VARCHAR(255) NULL,
    statutory_threshold VARCHAR(100) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_document_formulas_doc_id ON document_formulas(doc_id);
CREATE INDEX IF NOT EXISTS idx_document_formulas_name ON document_formulas(formula_name);
CREATE INDEX IF NOT EXISTS idx_document_formulas_document_id ON document_formulas(document_id);
