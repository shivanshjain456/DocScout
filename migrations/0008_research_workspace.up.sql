-- 0008: research_workspace — workspaces and synthesized research artifacts (P2-3).
--
-- Why: Complex analyst compliance queries require multi-aspect comparative synthesis
-- across regulatory provisions, generating structured markdown reports with condition
-- tables and auditable step traces. Workspaces provide persistence and versioning
-- for saved research artifacts.

SET search_path = public;

CREATE TABLE workspaces (
    workspace_id          uuid        PRIMARY KEY,
    name                  text        NOT NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  workspaces IS 'Research workspaces grouping analyst research sessions and artifacts (P2-3).';
COMMENT ON COLUMN workspaces.workspace_id IS 'Unique workspace identifier.';
COMMENT ON COLUMN workspaces.name IS 'Human-readable workspace title or project name.';

CREATE TABLE research_artifacts (
    artifact_id           uuid        PRIMARY KEY,
    workspace_id          uuid        NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    query                 text        NOT NULL,
    artifact_title        text        NOT NULL,
    content_markdown      text        NOT NULL,
    table_data            jsonb,
    steps                 jsonb       NOT NULL DEFAULT '[]'::jsonb,
    citations             jsonb       NOT NULL DEFAULT '[]'::jsonb,
    timings               jsonb       NOT NULL DEFAULT '{}'::jsonb,
    grounded              boolean     NOT NULL DEFAULT true,
    abstained             boolean     NOT NULL DEFAULT false,
    created_at            timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  research_artifacts IS 'Synthesized, citation-grounded research artifacts with auditable step traces (P2-3).';
COMMENT ON COLUMN research_artifacts.artifact_id IS 'Unique research artifact identifier.';
COMMENT ON COLUMN research_artifacts.query IS 'Original analyst compliance query.';
COMMENT ON COLUMN research_artifacts.content_markdown IS 'Full citation-grounded markdown analysis with condition tables.';
COMMENT ON COLUMN research_artifacts.steps IS 'Auditable trace of planner, tool execution, and critique steps.';
COMMENT ON COLUMN research_artifacts.citations IS 'List of cited chunk IDs and metadata.';

-- Default public workspace for general research sessions:
INSERT INTO workspaces (workspace_id, name)
VALUES ('00000000-0000-0000-0000-000000000000'::uuid, 'Default Regulatory Workspace')
ON CONFLICT (workspace_id) DO NOTHING;

CREATE INDEX idx_research_artifacts_ws ON research_artifacts(workspace_id, created_at DESC);
CREATE INDEX idx_research_artifacts_created ON research_artifacts(created_at DESC);

-- Least privilege: grant CRUD to application role:
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'docscout_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON workspaces, research_artifacts TO docscout_app;
    END IF;
END $$;
