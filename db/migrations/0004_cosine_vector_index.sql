-- The default vector index opclass serves only L2 (<->) ordering; the taint
-- engine's implicit-closure kNN orders by cosine (<=>), which full-scans against
-- the 0002 index (verified on v26.2.3, docs/plans/2026-07-03-week2.md section 1).
-- Rebuild with the cosine opclass so the kNN is genuinely index-backed.

DROP INDEX IF EXISTS beliefs_embedding_idx;

CREATE VECTOR INDEX beliefs_embedding_idx ON beliefs (embedding vector_cosine_ops);
