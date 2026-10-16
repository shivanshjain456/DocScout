-- 0012: layer_partitioning - taxonomy layer partitioning on chunks (FEAT-006).
--
-- Why: Partition lexical and dense search indexes across the 9 taxonomy layers
-- to enable isolated domain searches and lower vector search latency.

SET search_path = public;

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS taxonomy_layer text;

COMMENT ON COLUMN chunks.taxonomy_layer IS 'Taxonomy layer classification (1 of 9 layers from lexicon.json).';

-- Constraint checking allowed layers or NULL
ALTER TABLE chunks ADD CONSTRAINT ck_chunks_taxonomy_layer
    CHECK (taxonomy_layer IS NULL OR taxonomy_layer IN (
        'architecture-and-data',
        'delivery-and-platform',
        'frontiers',
        'intelligence-and-ai',
        'physical-and-regulated',
        'product-and-interface',
        'quality-and-verification',
        'reliability-and-operations',
        'security-and-trust'
    ));

-- Partial index for rapid layer-pruned scans
CREATE INDEX idx_chunks_layer ON chunks(taxonomy_layer) WHERE taxonomy_layer IS NOT NULL;

-- Default assignment: assign existing regulatory circular chunks to 'physical-and-regulated'
UPDATE chunks
   SET taxonomy_layer = 'physical-and-regulated'
 WHERE taxonomy_layer IS NULL;
