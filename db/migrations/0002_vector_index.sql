-- Distributed vector index for implicit taint tracing and similar-incident retrieval.
-- If the target cluster rejects this (older version or disabled feature), see
-- docs/spike-changefeeds.md for the fallback and do not silently skip it.

CREATE VECTOR INDEX beliefs_embedding_idx ON beliefs (embedding);
