-- Core SQL queries required by the experiment.
-- The placeholders use psql-style examples. Replace :member_id, :tree_id,
-- :member_a_id, and :member_b_id with concrete values before execution.

-- 1. Given a member id, query the member's spouses and children.
SELECT
    'spouse' AS relation,
    spouse.member_id,
    spouse.name,
    spouse.gender,
    spouse.birth_year,
    spouse.death_year,
    spouse.generation
FROM marriages ma
JOIN members target ON target.member_id = :member_id
JOIN members spouse
  ON spouse.member_id = CASE
      WHEN ma.spouse1_id = target.member_id THEN ma.spouse2_id
      ELSE ma.spouse1_id
  END
WHERE target.member_id IN (ma.spouse1_id, ma.spouse2_id)

UNION ALL

SELECT
    pc.relation_type || '_child' AS relation,
    child.member_id,
    child.name,
    child.gender,
    child.birth_year,
    child.death_year,
    child.generation
FROM parent_child pc
JOIN members child ON child.member_id = pc.child_id
WHERE pc.parent_id = :member_id
ORDER BY relation, generation, member_id;

-- 2. Recursive CTE: given member A, trace all ancestors upward.
WITH RECURSIVE ancestors AS (
    SELECT
        parent.member_id,
        parent.name,
        parent.gender,
        parent.birth_year,
        parent.death_year,
        parent.generation,
        pc.relation_type,
        1 AS distance,
        ARRAY[parent.member_id] AS path
    FROM parent_child pc
    JOIN members parent ON parent.member_id = pc.parent_id
    WHERE pc.child_id = :member_id

    UNION ALL

    SELECT
        grand_parent.member_id,
        grand_parent.name,
        grand_parent.gender,
        grand_parent.birth_year,
        grand_parent.death_year,
        grand_parent.generation,
        pc.relation_type,
        ancestors.distance + 1,
        ancestors.path || grand_parent.member_id
    FROM ancestors
    JOIN parent_child pc ON pc.child_id = ancestors.member_id
    JOIN members grand_parent ON grand_parent.member_id = pc.parent_id
    WHERE NOT grand_parent.member_id = ANY(ancestors.path)
)
SELECT *
FROM ancestors
ORDER BY distance, generation, member_id;

-- 3. Find the generation with the longest average lifespan in a family tree.
SELECT
    generation,
    ROUND(AVG(COALESCE(death_year, EXTRACT(YEAR FROM CURRENT_DATE)::INT) - birth_year), 2) AS avg_lifespan,
    COUNT(*) AS member_count
FROM members
WHERE tree_id = :tree_id
GROUP BY generation
HAVING COUNT(*) >= 2
ORDER BY avg_lifespan DESC, generation
LIMIT 1;

-- 4. Male members older than 50 who have no spouse.
SELECT
    m.member_id,
    m.name,
    m.birth_year,
    EXTRACT(YEAR FROM CURRENT_DATE)::INT - m.birth_year AS age,
    m.generation
FROM members m
WHERE m.tree_id = :tree_id
  AND m.gender = 'M'
  AND EXTRACT(YEAR FROM CURRENT_DATE)::INT - m.birth_year > 50
  AND NOT EXISTS (
      SELECT 1
      FROM marriages ma
      WHERE ma.spouse1_id = m.member_id
         OR ma.spouse2_id = m.member_id
  )
ORDER BY age DESC, m.member_id
LIMIT 100;

-- 5. Members born earlier than the average birth year of their generation.
WITH generation_avg AS (
    SELECT
        tree_id,
        generation,
        AVG(birth_year) AS avg_birth_year
    FROM members
    WHERE tree_id = :tree_id
    GROUP BY tree_id, generation
)
SELECT
    m.member_id,
    m.name,
    m.generation,
    m.birth_year,
    ROUND(g.avg_birth_year, 2) AS generation_avg_birth_year
FROM members m
JOIN generation_avg g
  ON g.tree_id = m.tree_id
 AND g.generation = m.generation
WHERE m.birth_year < g.avg_birth_year
ORDER BY m.generation, m.birth_year, m.member_id
LIMIT 100;

-- 6. Relationship path between two members in the same family tree.
WITH RECURSIVE
direct_spouse AS (
    SELECT
        ARRAY[:member_a_id::BIGINT, :member_b_id::BIGINT] AS path,
        ARRAY['spouse']::TEXT[] AS edge_labels,
        1 AS depth
    FROM marriages ma
    WHERE (ma.spouse1_id = LEAST(:member_a_id::BIGINT, :member_b_id::BIGINT)
       AND ma.spouse2_id = GREATEST(:member_a_id::BIGINT, :member_b_id::BIGINT))
),
up_from_a AS (
    SELECT
        :member_a_id::BIGINT AS current_id,
        ARRAY[:member_a_id::BIGINT] AS path,
        0 AS depth

    UNION ALL

    SELECT
        pc.parent_id,
        up_from_a.path || pc.parent_id,
        up_from_a.depth + 1
    FROM up_from_a
    JOIN parent_child pc ON pc.child_id = up_from_a.current_id
    WHERE up_from_a.depth < 12
      AND NOT pc.parent_id = ANY(up_from_a.path)
),
up_from_b AS (
    SELECT
        :member_b_id::BIGINT AS current_id,
        ARRAY[:member_b_id::BIGINT] AS path,
        0 AS depth

    UNION ALL

    SELECT
        pc.parent_id,
        up_from_b.path || pc.parent_id,
        up_from_b.depth + 1
    FROM up_from_b
    JOIN parent_child pc ON pc.child_id = up_from_b.current_id
    WHERE up_from_b.depth < 12
      AND NOT pc.parent_id = ANY(up_from_b.path)
),
blood_path AS (
    SELECT
        up_from_a.path ||
        ARRAY(
            SELECT item
            FROM unnest(up_from_b.path[1:GREATEST(cardinality(up_from_b.path) - 1, 0)]) WITH ORDINALITY AS path_item(item, ord)
            ORDER BY ord DESC
        ) AS path,
        up_from_a.depth + up_from_b.depth AS depth
    FROM up_from_a
    JOIN up_from_b ON up_from_b.current_id = up_from_a.current_id
    ORDER BY up_from_a.depth + up_from_b.depth
    LIMIT 1
),
best_path AS (
    SELECT path, edge_labels, depth
    FROM direct_spouse

    UNION ALL

    SELECT
        path,
        array_fill('blood relation'::TEXT, ARRAY[GREATEST(depth, 0)]) AS edge_labels,
        depth
    FROM blood_path
)
SELECT
    path,
    edge_labels,
    depth
FROM best_path
ORDER BY depth
LIMIT 1;
