-- Bind propagated provenance to every new belief attestation while retaining
-- verification compatibility with the v1 rows created before Recant Guard.

ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS context_receipt_id UUID REFERENCES context_receipts (receipt_id);
ALTER TABLE beliefs ADD COLUMN IF NOT EXISTS attestation_version STRING NOT NULL DEFAULT 'v1';

ALTER TABLE agent_actions ADD CONSTRAINT IF NOT EXISTS agent_actions_decision_fk
    FOREIGN KEY (decision_id) REFERENCES action_decisions (decision_id);
ALTER TABLE agent_actions ADD CONSTRAINT IF NOT EXISTS agent_actions_permit_fk
    FOREIGN KEY (permit_id) REFERENCES action_permits (permit_id);

-- Earlier rows predate numeric authority. Reconstruct their least-authority
-- provenance from every reachable source so Guard cannot over-trust a legacy
-- derived memory after an upgrade.
UPDATE sources
SET authority_rank = CASE trust_tier
    WHEN 'verified' THEN 60
    WHEN 'partner' THEN 40
    WHEN 'public' THEN 20
    ELSE 10
END;

WITH RECURSIVE lineage (tenant_id, belief_id, ancestor_id) AS (
    SELECT tenant_id, belief_id, belief_id
    FROM beliefs
    UNION
    SELECT l.tenant_id, l.belief_id, d.parent_id
    FROM lineage AS l
    JOIN derivations AS d
      ON d.tenant_id = l.tenant_id
     AND d.child_id = l.ancestor_id
    WHERE d.kind = 'explicit'
), provenance AS (
    SELECT
        l.tenant_id,
        l.belief_id,
        min(s.authority_rank) AS authority_rank,
        array_agg(DISTINCT s.source_id) AS origin_source_ids
    FROM lineage AS l
    JOIN beliefs AS ancestor
      ON ancestor.tenant_id = l.tenant_id
     AND ancestor.belief_id = l.ancestor_id
    JOIN sources AS s
      ON s.tenant_id = ancestor.tenant_id
     AND s.source_id = ancestor.source_id
    GROUP BY l.tenant_id, l.belief_id
)
UPDATE beliefs AS b
SET authority_rank = p.authority_rank,
    origin_source_ids = p.origin_source_ids
FROM provenance AS p
WHERE b.tenant_id = p.tenant_id
  AND b.belief_id = p.belief_id;
