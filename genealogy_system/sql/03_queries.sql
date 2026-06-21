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

-- 2. Recursive CTE: given member A, trace all unique ancestors upward.
WITH RECURSIVE
target_member AS (
    SELECT member_id, generation
    FROM members
    WHERE member_id = :member_id
),
ancestor_steps AS (
    SELECT
        pc.parent_id AS member_id,
        1 AS distance
    FROM parent_child pc
    JOIN members parent ON parent.member_id = pc.parent_id
    JOIN target_member target ON target.member_id = pc.child_id
    WHERE parent.generation < target.generation

    UNION

    SELECT
        pc.parent_id AS member_id,
        ancestor_steps.distance + 1 AS distance
    FROM ancestor_steps
    JOIN members current_member ON current_member.member_id = ancestor_steps.member_id
    JOIN parent_child pc ON pc.child_id = ancestor_steps.member_id
    JOIN members parent ON parent.member_id = pc.parent_id
    WHERE parent.generation < current_member.generation
),
ancestor_branches AS (
    SELECT
        pc.parent_id AS member_id,
        pc.relation_type AS root_relation_type
    FROM parent_child pc
    JOIN members parent ON parent.member_id = pc.parent_id
    JOIN target_member target ON target.member_id = pc.child_id
    WHERE parent.generation < target.generation

    UNION

    SELECT
        pc.parent_id AS member_id,
        ancestor_branches.root_relation_type
    FROM ancestor_branches
    JOIN members current_member ON current_member.member_id = ancestor_branches.member_id
    JOIN parent_child pc ON pc.child_id = ancestor_branches.member_id
    JOIN members parent ON parent.member_id = pc.parent_id
    WHERE parent.generation < current_member.generation
),
shortest AS (
    SELECT member_id, MIN(distance) AS distance
    FROM ancestor_steps
    GROUP BY member_id
),
branches AS (
    SELECT
        member_id,
        BOOL_OR(root_relation_type = 'father') AS via_father,
        BOOL_OR(root_relation_type = 'mother') AS via_mother
    FROM ancestor_branches
    GROUP BY member_id
)
SELECT
    m.member_id,
    m.name,
    m.gender,
    m.birth_year,
    m.death_year,
    m.generation,
    shortest.distance,
    GREATEST(target.generation - m.generation, 0) AS generation_gap,
    CASE
        WHEN COALESCE(branches.via_father, FALSE)
         AND COALESCE(branches.via_mother, FALSE) THEN '父系/母系'
        WHEN COALESCE(branches.via_father, FALSE) THEN '父系'
        WHEN COALESCE(branches.via_mother, FALSE) THEN '母系'
        ELSE '未知'
    END AS lineage_label
FROM shortest
JOIN members m ON m.member_id = shortest.member_id
CROSS JOIN target_member target
LEFT JOIN branches ON branches.member_id = shortest.member_id
ORDER BY shortest.distance, m.generation DESC, m.member_id;

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
WITH male_members AS (
    SELECT
        m.member_id,
        m.name,
        m.birth_year,
        m.death_year,
        CASE
            WHEN m.death_year IS NULL THEN
                EXTRACT(YEAR FROM AGE(CURRENT_DATE, MAKE_DATE(m.birth_year, 1, 1)))::INT
            ELSE m.death_year - m.birth_year
        END AS age,
        CASE
            WHEN m.death_year IS NULL THEN '年龄'
            ELSE '享年'
        END AS age_label,
        m.generation
    FROM members m
    WHERE m.tree_id = :tree_id
      AND m.gender = 'M'
      AND NOT EXISTS (
          SELECT 1
          FROM marriages ma
          WHERE ma.tree_id = m.tree_id
            AND (ma.spouse1_id = m.member_id OR ma.spouse2_id = m.member_id)
      )
)
SELECT
    member_id,
    name,
    birth_year,
    death_year,
    age,
    age_label,
    generation
FROM male_members
WHERE age > 50
ORDER BY age DESC, generation, member_id
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
