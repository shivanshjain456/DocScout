-- Revert 0003: drop corpus_sync_state.

SET search_path = public;

DROP TABLE IF EXISTS corpus_sync_state;
