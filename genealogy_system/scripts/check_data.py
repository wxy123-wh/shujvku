"""Validate generated CSV files before PostgreSQL import."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def read_csv(name: str) -> list[dict[str, str]]:
    path = DATA_DIR / name
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def main() -> None:
    members = read_csv("members.csv")
    parent_child = read_csv("parent_child.csv")
    marriages = read_csv("marriages.csv")
    family_trees = read_csv("family_trees.csv")
    users = read_csv("users.csv")
    collaborators = read_csv("tree_collaborators.csv")

    member_map = {int(row["member_id"]): row for row in members}
    tree_ids = {int(row["tree_id"]) for row in family_trees}
    user_ids = {int(row["user_id"]) for row in users}
    errors: list[str] = []

    for row in family_trees:
        if int(row["creator_user_id"]) not in user_ids:
            errors.append(f"family_trees creator missing: {row}")

    for row in collaborators:
        if int(row["tree_id"]) not in tree_ids:
            errors.append(f"collaborator tree missing: {row}")
        if int(row["user_id"]) not in user_ids:
            errors.append(f"collaborator user missing: {row}")
        if row["role"] not in {"owner", "editor", "viewer"}:
            errors.append(f"collaborator role invalid: {row}")

    for row in members:
        birth_year = int(row["birth_year"])
        generation = int(row["generation"])
        if int(row["tree_id"]) not in tree_ids:
            errors.append(f"member tree missing: {row['member_id']}")
        if row["gender"] not in {"M", "F"}:
            errors.append(f"member gender invalid: {row['member_id']}")
        if not 1000 <= birth_year <= 2200:
            errors.append(f"member birth year invalid: {row['member_id']}")
        if row["death_year"] and int(row["death_year"]) < birth_year:
            errors.append(f"member death year invalid: {row['member_id']}")
        if generation < 1:
            errors.append(f"member generation invalid: {row['member_id']}")

    parent_type_by_child = Counter((row["child_id"], row["relation_type"]) for row in parent_child)
    for key, count in parent_type_by_child.items():
        if count > 1:
            errors.append(f"child has duplicate parent type: {key}")

    for row in parent_child:
        parent = member_map.get(int(row["parent_id"]))
        child = member_map.get(int(row["child_id"]))
        if not parent or not child:
            errors.append(f"parent_child member missing: {row}")
            continue
        if parent["tree_id"] != child["tree_id"]:
            errors.append(f"parent_child tree mismatch: {row}")
        if row["relation_type"] == "father" and parent["gender"] != "M":
            errors.append(f"father gender invalid: {row}")
        if row["relation_type"] == "mother" and parent["gender"] != "F":
            errors.append(f"mother gender invalid: {row}")
        if int(parent["birth_year"]) >= int(child["birth_year"]):
            errors.append(f"parent birth year invalid: {row}")
        if int(parent["generation"]) >= int(child["generation"]):
            errors.append(f"parent generation invalid: {row}")

    marriage_pairs = Counter((row["tree_id"], row["spouse1_id"], row["spouse2_id"]) for row in marriages)
    for key, count in marriage_pairs.items():
        if count > 1:
            errors.append(f"duplicate marriage pair: {key}")

    for row in marriages:
        spouse1 = member_map.get(int(row["spouse1_id"]))
        spouse2 = member_map.get(int(row["spouse2_id"]))
        if int(row["spouse1_id"]) >= int(row["spouse2_id"]):
            errors.append(f"marriage pair is not canonical: {row}")
        if not spouse1 or not spouse2:
            errors.append(f"marriage member missing: {row}")
            continue
        if spouse1["tree_id"] != spouse2["tree_id"] or spouse1["tree_id"] != row["tree_id"]:
            errors.append(f"marriage tree mismatch: {row}")

    by_tree = Counter(int(row["tree_id"]) for row in members)
    max_generation = {}
    for row in members:
        tree_id = int(row["tree_id"])
        max_generation[tree_id] = max(max_generation.get(tree_id, 0), int(row["generation"]))

    if len(by_tree) < 10:
        errors.append("fewer than 10 family trees have members")
    if sum(by_tree.values()) < 100000:
        errors.append("member count is below 100,000")
    if max(by_tree.values(), default=0) <= 50000:
        errors.append("no family tree has more than 50,000 members")
    if max(max_generation.values(), default=0) < 30:
        errors.append("no family tree has at least 30 generations")

    print(f"users: {len(users)}")
    print(f"family_trees: {len(family_trees)}")
    print(f"members: {len(members)}")
    print(f"parent_child: {len(parent_child)}")
    print(f"marriages: {len(marriages)}")
    print(f"members by tree: {dict(sorted(by_tree.items()))}")
    print(f"max generation by tree: {dict(sorted(max_generation.items()))}")

    if errors:
        print(f"errors: {len(errors)}")
        for error in errors[:20]:
            print(error)
        raise SystemExit(1)
    print("CSV validation passed.")


if __name__ == "__main__":
    main()
