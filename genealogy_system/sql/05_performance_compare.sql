-- Query used for the required "with index vs without index" performance comparison.
-- Replace :ancestor_id with a real member id before running, or set it in psql:
--   \set ancestor_id 1

EXPLAIN ANALYZE
WITH RECURSIVE descendants AS (
    SELECT
        m.member_id,
        m.name,
        0 AS depth,
        ARRAY[m.member_id] AS path
    FROM members m
    WHERE m.member_id = :ancestor_id

    UNION ALL

    SELECT
        child.member_id,
        child.name,
        descendants.depth + 1 AS depth,
        descendants.path || child.member_id
    FROM descendants
    JOIN parent_child pc ON pc.parent_id = descendants.member_id
    JOIN members child ON child.member_id = pc.child_id
    WHERE descendants.depth < 4
      AND NOT child.member_id = ANY(descendants.path)
)
SELECT *
FROM descendants
WHERE depth = 4
ORDER BY member_id;
