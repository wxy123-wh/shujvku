-- Indexes for search, recursive lineage queries, and statistics.
-- Run after sql/01_schema.sql and data import.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_family_trees_creator ON family_trees(creator_user_id);
CREATE INDEX IF NOT EXISTS idx_tree_collaborators_user ON tree_collaborators(user_id, tree_id);
CREATE INDEX IF NOT EXISTS idx_members_tree_name ON members(tree_id, name);
CREATE INDEX IF NOT EXISTS idx_members_name_trgm ON members USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_members_tree_generation ON members(tree_id, generation);
CREATE INDEX IF NOT EXISTS idx_members_tree_gender ON members(tree_id, gender);
CREATE INDEX IF NOT EXISTS idx_parent_child_parent ON parent_child(parent_id);
CREATE INDEX IF NOT EXISTS idx_parent_child_child ON parent_child(child_id);
CREATE INDEX IF NOT EXISTS idx_marriages_spouse1 ON marriages(spouse1_id);
CREATE INDEX IF NOT EXISTS idx_marriages_spouse2 ON marriages(spouse2_id);
