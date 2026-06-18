"""Generate CSV data for the genealogy management system.

The default dataset follows the experiment requirements:
- at least 10 family trees
- more than 100,000 members in total
- one tree with more than 50,000 members
- one tree with at least 30 generations

Run from the genealogy_system directory:
    python scripts/generate_data.py
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from werkzeug.security import generate_password_hash
except Exception:  # pragma: no cover - only used before dependencies are installed.
    generate_password_hash = None


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

SURNAMES = ["王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴"]
GIVEN_CHARS = ["明", "华", "强", "芳", "军", "伟", "敏", "磊", "丽", "涛", "娜", "杰"]
GENERATION_CHARS = list("德承宗祖世家国文章永昌仁义礼智信忠孝传芳")
TREE_SIZES = [60000, 10000, 8000, 6000, 5000, 4000, 3000, 2000, 1500, 1000]
TREE_GENERATIONS = [32, 18, 16, 14, 12, 12, 10, 10, 8, 8]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: ("" if row.get(key) is None else row.get(key)) for key in fieldnames})


def distribute_generation_counts(total: int, generations: int) -> list[int]:
    base = total // generations
    remainder = total % generations
    counts = [base + (1 if index < remainder else 0) for index in range(generations)]

    # Keep every generation large enough to contain at least one father and one mother.
    for index, count in enumerate(counts):
        if count < 2:
            counts[index] = 2

    diff = sum(counts) - total
    index = len(counts) - 1
    while diff > 0 and index >= 0:
        removable = max(0, counts[index] - 2)
        take = min(removable, diff)
        counts[index] -= take
        diff -= take
        index -= 1
    return counts


def gender_for(index: int) -> str:
    return "M" if index % 2 == 0 else "F"


def member_name(surname: str, generation: int, index: int) -> str:
    generation_char = GENERATION_CHARS[(generation - 1) % len(GENERATION_CHARS)]
    given_char = GIVEN_CHARS[index % len(GIVEN_CHARS)]
    return f"{surname}{generation_char}{given_char}{index % 1000:03d}"


def build_users() -> tuple[list[dict[str, object]], str]:
    if generate_password_hash:
        password_hash = generate_password_hash("123456")
    else:
        password_hash = "plain:123456"

    users = []
    for user_id in range(1, 7):
        users.append(
            {
                "user_id": user_id,
                "username": f"user{user_id}",
                "password_hash": password_hash,
                "created_at": NOW,
            }
        )
    return users, password_hash


def member_id(member: dict[str, object]) -> int:
    return int(member["member_id"])


def spouse_pair(first: dict[str, object], second: dict[str, object]) -> tuple[int, int]:
    return tuple(sorted((member_id(first), member_id(second))))


def can_marry(
    first: dict[str, object],
    second: dict[str, object],
    parent_sets: dict[int, set[int]],
    existing_pairs: set[tuple[int, int]],
) -> bool:
    first_id, second_id = spouse_pair(first, second)
    if first_id == second_id or (first_id, second_id) in existing_pairs:
        return False
    if first["gender"] == second["gender"]:
        return False
    return not (parent_sets.get(first_id, set()) & parent_sets.get(second_id, set()))


def build_spouse_couples(
    generation_members: list[dict[str, object]],
    parent_sets: dict[int, set[int]],
    existing_pairs: set[tuple[int, int]],
) -> list[tuple[dict[str, object], dict[str, object]]]:
    males = [item for item in generation_members if item["gender"] == "M"]
    females = [item for item in generation_members if item["gender"] == "F"]
    couples: list[tuple[dict[str, object], dict[str, object]]] = []
    if not males or not females:
        return couples

    for index, male in enumerate(males):
        for shift in range(len(females)):
            female = females[(index + shift) % len(females)]
            if can_marry(male, female, parent_sets, existing_pairs):
                couples.append((male, female))
                existing_pairs.add(spouse_pair(male, female))
                break
    return couples


def generate(seed: int = 20260618) -> None:
    random.seed(seed)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    users, _ = build_users()
    family_trees: list[dict[str, object]] = []
    collaborators: list[dict[str, object]] = []
    members: list[dict[str, object]] = []
    parent_child: list[dict[str, object]] = []
    marriages: list[dict[str, object]] = []

    next_member_id = 1
    next_marriage_id = 1

    for tree_index, (tree_size, generation_count) in enumerate(zip(TREE_SIZES, TREE_GENERATIONS), start=1):
        surname = SURNAMES[tree_index - 1]
        creator_user_id = ((tree_index - 1) % len(users)) + 1
        family_trees.append(
            {
                "tree_id": tree_index,
                "tree_name": f"{surname}氏族谱第{tree_index}卷",
                "surname": surname,
                "revision_time": f"2026-{((tree_index - 1) % 12) + 1:02d}-01",
                "creator_user_id": creator_user_id,
                "created_at": NOW,
            }
        )
        collaborators.append(
            {
                "tree_id": tree_index,
                "user_id": creator_user_id,
                "role": "owner",
                "created_at": NOW,
            }
        )
        invited_user_id = (creator_user_id % len(users)) + 1
        collaborators.append(
            {
                "tree_id": tree_index,
                "user_id": invited_user_id,
                "role": "editor",
                "created_at": NOW,
            }
        )

        generation_counts = distribute_generation_counts(tree_size, generation_count)
        previous_couples: list[tuple[dict[str, object], dict[str, object]]] = []
        parent_sets: dict[int, set[int]] = {}
        marriage_pairs: set[tuple[int, int]] = set()

        for generation, generation_size in enumerate(generation_counts, start=1):
            current_generation: list[dict[str, object]] = []
            birth_base = 1200 + (generation - 1) * 25 + tree_index

            for index in range(generation_size):
                gender = gender_for(index)
                birth_year = birth_base + random.randint(-2, 2)
                death_year = None
                if birth_year < 1970:
                    death_year = birth_year + random.randint(58, 88)

                member = {
                    "member_id": next_member_id,
                    "tree_id": tree_index,
                    "name": member_name(surname, generation, index),
                    "gender": gender,
                    "birth_year": birth_year,
                    "death_year": death_year,
                    "generation": generation,
                    "biography": f"{surname}氏第{generation}代成员，模拟数据编号{next_member_id}。",
                    "created_at": NOW,
                }
                members.append(member)
                current_generation.append(member)
                parent_sets[member_id(member)] = set()

                if previous_couples:
                    father, mother = previous_couples[index % len(previous_couples)]
                    parent_sets[member_id(member)] = {member_id(father), member_id(mother)}

                    parent_child.append(
                        {
                            "parent_id": father["member_id"],
                            "child_id": member["member_id"],
                            "relation_type": "father",
                        }
                    )
                    parent_child.append(
                        {
                            "parent_id": mother["member_id"],
                            "child_id": member["member_id"],
                            "relation_type": "mother",
                        }
                    )

                next_member_id += 1

            current_couples = build_spouse_couples(current_generation, parent_sets, marriage_pairs)
            for spouse1, spouse2 in current_couples:
                spouse1_id, spouse2_id = spouse_pair(spouse1, spouse2)
                marriages.append(
                    {
                        "marriage_id": next_marriage_id,
                        "tree_id": tree_index,
                        "spouse1_id": spouse1_id,
                        "spouse2_id": spouse2_id,
                        "marriage_year": min(int(spouse1["birth_year"]), int(spouse2["birth_year"])) + 22,
                    }
                )
                next_marriage_id += 1

            previous_couples = current_couples

    write_csv(DATA_DIR / "users.csv", ["user_id", "username", "password_hash", "created_at"], users)
    write_csv(
        DATA_DIR / "family_trees.csv",
        ["tree_id", "tree_name", "surname", "revision_time", "creator_user_id", "created_at"],
        family_trees,
    )
    write_csv(
        DATA_DIR / "tree_collaborators.csv",
        ["tree_id", "user_id", "role", "created_at"],
        collaborators,
    )
    write_csv(
        DATA_DIR / "members.csv",
        [
            "member_id",
            "tree_id",
            "name",
            "gender",
            "birth_year",
            "death_year",
            "generation",
            "biography",
            "created_at",
        ],
        members,
    )
    write_csv(DATA_DIR / "parent_child.csv", ["parent_id", "child_id", "relation_type"], parent_child)
    write_csv(
        DATA_DIR / "marriages.csv",
        ["marriage_id", "tree_id", "spouse1_id", "spouse2_id", "marriage_year"],
        marriages,
    )

    by_tree: dict[int, int] = defaultdict(int)
    by_generation: dict[int, int] = defaultdict(int)
    for member in members:
        by_tree[int(member["tree_id"])] += 1
        by_generation[int(member["tree_id"])] = max(by_generation[int(member["tree_id"])], int(member["generation"]))

    print(f"Generated {len(members):,} members")
    print(f"Generated {len(parent_child):,} parent-child rows")
    print(f"Generated {len(marriages):,} marriage rows")
    print("Members by tree:", dict(sorted(by_tree.items())))
    print("Max generations:", dict(sorted(by_generation.items())))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260618, help="Random seed for reproducible CSV output.")
    args = parser.parse_args()
    generate(args.seed)


if __name__ == "__main__":
    main()
