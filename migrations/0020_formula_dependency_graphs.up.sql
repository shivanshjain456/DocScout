-- Migration 0020: Formula Dependency Graphs Table (FEAT-029)
-- Stores regulatory calculation graphs, variable dependencies, and topological execution tiers.

CREATE TABLE IF NOT EXISTS formula_dependency_graphs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT 'banking', -- 'banking', 'liquidity', 'climate', 'custom'
    description TEXT NOT NULL,
    root_target_variables JSONB NOT NULL DEFAULT '[]'::jsonb,
    nodes JSONB NOT NULL DEFAULT '[]'::jsonb,
    edges JSONB NOT NULL DEFAULT '[]'::jsonb,
    topological_order JSONB NOT NULL DEFAULT '[]'::jsonb,
    execution_tiers JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_template BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dep_graphs_domain ON formula_dependency_graphs(domain);
CREATE INDEX IF NOT EXISTS idx_dep_graphs_is_template ON formula_dependency_graphs(is_template);
