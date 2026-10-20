-- Migration 0054 down: Revoke permissions on feature tables from docscout_app role

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docscout_app') THEN
        REVOKE ALL ON
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
        FROM docscout_app;
    END IF;
END $$;
