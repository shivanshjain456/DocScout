-- Migration 0026: Sunset Clause & Mandatory Cutover Alerting (FEAT-035)
-- Stores extracted milestone dates, sunset clauses, and mandatory transition cutovers.

CREATE TABLE IF NOT EXISTS regulatory_deadlines (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    mandate_description TEXT NOT NULL,
    effective_date DATE NOT NULL,
    extracted_snippet TEXT,
    urgency_level TEXT NOT NULL DEFAULT 'INFO',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS deadline_alert_history (
    id TEXT PRIMARY KEY,
    deadline_id TEXT NOT NULL REFERENCES regulatory_deadlines(id) ON DELETE CASCADE,
    doc_id TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'EMAIL',
    urgency_level TEXT NOT NULL,
    days_remaining INT NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    brevo_message_id TEXT,
    delivery_status TEXT NOT NULL DEFAULT 'SENT'
);

CREATE INDEX IF NOT EXISTS idx_regulatory_deadlines_doc ON regulatory_deadlines(doc_id);
CREATE INDEX IF NOT EXISTS idx_regulatory_deadlines_effective_date ON regulatory_deadlines(effective_date);
CREATE INDEX IF NOT EXISTS idx_regulatory_deadlines_urgency ON regulatory_deadlines(urgency_level);
CREATE INDEX IF NOT EXISTS idx_deadline_alert_history_deadline ON deadline_alert_history(deadline_id);
CREATE INDEX IF NOT EXISTS idx_deadline_alert_history_sent ON deadline_alert_history(sent_at);
