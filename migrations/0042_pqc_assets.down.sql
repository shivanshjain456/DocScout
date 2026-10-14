-- Migration 0042 Down: Post-Quantum Cryptographic Migration Tracker (FEAT-057)

SET search_path = public;

DROP TABLE IF EXISTS pqc_crypto_assets CASCADE;
