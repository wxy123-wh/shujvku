-- Import generated CSV files.
-- Run from the genealogy_system directory after creating tables:
--   psql -U postgres -d genealogy_db -f sql/04_import.sql

\copy users(user_id, username, password_hash, created_at) FROM 'data/users.csv' WITH (FORMAT csv, HEADER true, NULL '');
\copy family_trees(tree_id, tree_name, surname, revision_time, creator_user_id, created_at) FROM 'data/family_trees.csv' WITH (FORMAT csv, HEADER true, NULL '');
\copy tree_collaborators(tree_id, user_id, role, created_at) FROM 'data/tree_collaborators.csv' WITH (FORMAT csv, HEADER true, NULL '');
\copy members(member_id, tree_id, name, gender, birth_year, death_year, generation, biography, created_at) FROM 'data/members.csv' WITH (FORMAT csv, HEADER true, NULL '');
\copy parent_child(parent_id, child_id, relation_type) FROM 'data/parent_child.csv' WITH (FORMAT csv, HEADER true, NULL '');
\copy marriages(marriage_id, tree_id, spouse1_id, spouse2_id, marriage_year) FROM 'data/marriages.csv' WITH (FORMAT csv, HEADER true, NULL '');

SELECT setval(pg_get_serial_sequence('users', 'user_id'), COALESCE(MAX(user_id), 1), true) FROM users;
SELECT setval(pg_get_serial_sequence('family_trees', 'tree_id'), COALESCE(MAX(tree_id), 1), true) FROM family_trees;
SELECT setval(pg_get_serial_sequence('members', 'member_id'), COALESCE(MAX(member_id), 1), true) FROM members;
SELECT setval(pg_get_serial_sequence('marriages', 'marriage_id'), COALESCE(MAX(marriage_id), 1), true) FROM marriages;

SELECT COUNT(*) AS total_members FROM members;
SELECT tree_id, COUNT(*) AS member_count FROM members GROUP BY tree_id ORDER BY member_count DESC;
SELECT tree_id, MAX(generation) AS max_generation FROM members GROUP BY tree_id ORDER BY max_generation DESC;
