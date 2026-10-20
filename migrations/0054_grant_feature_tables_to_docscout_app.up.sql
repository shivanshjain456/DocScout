-- Migration 0054: Grant permissions on feature tables to least-privilege docscout_app role

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docscout_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON
            antipattern_definitions,
            antipattern_scan_audits,
            circular_clauses,
            clause_conflict_audits,
            compliance_debt_audit_log,
            compliance_debt_register,
            deadline_alert_history,
            document_formulas,
            financial_unit_scales,
            formula_dependency_graphs,
            formula_versions,
            mathematical_audit_logs,
            ontology_staging,
            prescriptive_remediations,
            regulatory_deadlines,
            remediation_audit_logs,
            statutory_deprecations,
            statutory_parameters
        TO docscout_app;
    END IF;
END $$;
