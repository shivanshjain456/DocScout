-- Migration 0052 Down: Drop canary_tokens table (FEAT-084)

SET search_path = public;

DROP TABLE IF EXISTS canary_tokens CASCADE;
