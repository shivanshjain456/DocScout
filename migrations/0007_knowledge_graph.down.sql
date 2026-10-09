-- 0007: revert knowledge_graph tables (P2-2).

SET search_path = public;

DROP TABLE IF EXISTS graph_edges;
DROP TABLE IF EXISTS graph_nodes;
