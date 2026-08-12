-- Keep approximate nearest-neighbor candidates inside the tenant boundary.
-- CockroachDB vector indexes support non-vector prefix columns when every
-- indexed query constrains those columns.

DROP INDEX IF EXISTS beliefs_embedding_idx;
CREATE VECTOR INDEX beliefs_embedding_idx
    ON beliefs (tenant_id, embedding vector_cosine_ops);
