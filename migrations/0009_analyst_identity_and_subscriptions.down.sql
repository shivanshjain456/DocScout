-- DocScout 0009: rollback analyst identity, subscriptions, and OCR cache.

SET search_path = public;

DROP TABLE IF EXISTS ocr_extractions;
DROP TABLE IF EXISTS digest_deliveries;
DROP TABLE IF EXISTS subscription_topics;
DROP TABLE IF EXISTS subscriptions;
DROP TABLE IF EXISTS user_interests;
DROP TABLE IF EXISTS users;
