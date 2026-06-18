from __future__ import annotations

import os
from functools import wraps
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/genealogy_db",
)
PAGE_SIZE_OPTIONS = [10, 20, 50, 100, 200, 500, 1000, 2000]

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")


def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with get_db().cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


def query_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with get_db().cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None


def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(sql, params)
    db.commit()


def verify_password(stored_hash: str, password: str) -> bool:
    if stored_hash.startswith("plain:"):
        return stored_hash == f"plain:{password}"
    try:
        return check_password_hash(stored_hash, password)
    except ValueError:
        return False


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if "user_id" not in session:
            flash("请先登录。", "warning")
            return redirect(url_for("login", next=request.path))
        return view(**kwargs)

    return wrapped_view


@app.context_processor
def inject_current_user():
    return {"current_user": session.get("username")}


def get_accessible_tree(tree_id: int, write: bool = False, owner: bool = False) -> dict[str, Any] | None:
    user_id = session["user_id"]
    role_filter = ""
    if owner:
        role_filter = "AND (t.creator_user_id = %s OR tc.role = 'owner')"
    elif write:
        role_filter = "AND (t.creator_user_id = %s OR tc.role IN ('owner', 'editor'))"

    params: tuple[Any, ...]
    if role_filter:
        params = (user_id, user_id, tree_id, user_id, user_id, user_id)
    else:
        params = (user_id, user_id, tree_id, user_id, user_id)

    sql = f"""
        SELECT
            t.*,
            CASE WHEN t.creator_user_id = %s THEN 'owner' ELSE tc.role END AS current_role
        FROM family_trees t
        LEFT JOIN tree_collaborators tc
          ON tc.tree_id = t.tree_id
         AND tc.user_id = %s
        WHERE t.tree_id = %s
          AND (t.creator_user_id = %s OR tc.user_id = %s)
          {role_filter}
    """
    return query_one(sql, params)


def require_tree(tree_id: int, write: bool = False, owner: bool = False) -> dict[str, Any]:
    tree = get_accessible_tree(tree_id, write=write, owner=owner)
    if not tree:
        flash("没有权限访问该族谱。", "danger")
        raise PermissionError
    return tree


def parse_int(value: str | None, field_name: str, required: bool = False) -> int | None:
    if value is None or value.strip() == "":
        if required:
            raise ValueError(f"{field_name}不能为空。")
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name}必须是整数。") from exc


def get_pagination(default_size: int = 200) -> tuple[int, int]:
    try:
        page = int(request.args.get("page", "1") or 1)
    except ValueError:
        page = 1
    try:
        page_size = int(request.args.get("page_size", str(default_size)) or default_size)
    except ValueError:
        page_size = default_size
    page = max(page, 1)
    page_size = min(max(page_size, min(PAGE_SIZE_OPTIONS)), max(PAGE_SIZE_OPTIONS))
    return page, page_size


def pagination_context(total_count: int, page: int, page_size: int, row_count: int) -> dict[str, int | list[int]]:
    total_pages = max((total_count + page_size - 1) // page_size, 1)
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * page_size
    return {
        "page": page,
        "page_size": page_size,
        "page_size_options": PAGE_SIZE_OPTIONS,
        "total_pages": total_pages,
        "start_row": offset + 1 if total_count else 0,
        "end_row": min(offset + row_count, total_count),
    }


def normalize_pair(first_id: int, second_id: int) -> tuple[int, int]:
    if first_id == second_id:
        raise ValueError("配偶不能是自己。")
    return (first_id, second_id) if first_id < second_id else (second_id, first_id)


def fetch_member(tree_id: int, member_id: int) -> dict[str, Any] | None:
    return query_one(
        """
        SELECT *
        FROM members
        WHERE tree_id = %s AND member_id = %s
        """,
        (tree_id, member_id),
    )


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3:
            flash("用户名至少 3 个字符。", "danger")
        elif len(password) < 6:
            flash("密码至少 6 个字符。", "danger")
        else:
            db = get_db()
            try:
                with db.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO users(username, password_hash)
                        VALUES (%s, %s)
                        RETURNING user_id
                        """,
                        (username, generate_password_hash(password)),
                    )
                    user_id = cursor.fetchone()["user_id"]
                db.commit()
                session.clear()
                session["user_id"] = user_id
                session["username"] = username
                flash("注册成功。", "success")
                return redirect(url_for("dashboard"))
            except psycopg2.IntegrityError:
                db.rollback()
                flash("用户名已存在。", "danger")
    return render_template("register.html")


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = query_one("SELECT * FROM users WHERE username = %s", (username,))
        if user and verify_password(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            flash("登录成功。", "success")
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("用户名或密码错误。", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("已退出登录。", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    page, page_size = get_pagination(default_size=20)
    stats = query_one(
        """
        WITH visible_trees AS (
            SELECT DISTINCT t.tree_id
            FROM family_trees t
            LEFT JOIN tree_collaborators tc
              ON tc.tree_id = t.tree_id
             AND tc.user_id = %s
            WHERE t.creator_user_id = %s OR tc.user_id = %s
        )
        SELECT
            COUNT(DISTINCT vt.tree_id) AS tree_count,
            COUNT(m.member_id) AS member_count,
            COUNT(m.member_id) FILTER (WHERE m.gender = 'M') AS male_count,
            COUNT(m.member_id) FILTER (WHERE m.gender = 'F') AS female_count
        FROM visible_trees vt
        LEFT JOIN members m ON m.tree_id = vt.tree_id
        """,
        (user_id, user_id, user_id),
    )
    if stats:
        male_count = stats.get("male_count") or 0
        female_count = stats.get("female_count") or 0
        stats["gender_ratio"] = f"{male_count}:{female_count}" if male_count or female_count else "0:0"
    tree_total = query_one(
        """
        SELECT COUNT(DISTINCT t.tree_id) AS count
        FROM family_trees t
        LEFT JOIN tree_collaborators tc
          ON tc.tree_id = t.tree_id
         AND tc.user_id = %s
        WHERE t.creator_user_id = %s OR tc.user_id = %s
        """,
        (user_id, user_id, user_id),
    )
    tree_count = tree_total["count"] if tree_total else 0
    page_info = pagination_context(tree_count, page, page_size, 0)
    offset = (page_info["page"] - 1) * page_size
    trees = query_all(
        """
        SELECT
            t.tree_id,
            t.tree_name,
            t.surname,
            t.revision_time,
            CASE WHEN t.creator_user_id = %s THEN 'owner' ELSE tc.role END AS current_role,
            COUNT(m.member_id) AS member_count
        FROM family_trees t
        LEFT JOIN tree_collaborators tc
          ON tc.tree_id = t.tree_id
         AND tc.user_id = %s
        LEFT JOIN members m ON m.tree_id = t.tree_id
        WHERE t.creator_user_id = %s OR tc.user_id = %s
        GROUP BY t.tree_id, tc.role
        ORDER BY t.tree_id
        LIMIT %s OFFSET %s
        """,
        (user_id, user_id, user_id, user_id, page_size, offset),
    )
    page_info = pagination_context(tree_count, int(page_info["page"]), page_size, len(trees))
    return render_template("dashboard.html", stats=stats or {}, trees=trees, tree_count=tree_count, **page_info)


@app.route("/trees")
@login_required
def trees():
    user_id = session["user_id"]
    page, page_size = get_pagination(default_size=20)
    total = query_one(
        """
        SELECT COUNT(DISTINCT t.tree_id) AS count
        FROM family_trees t
        LEFT JOIN tree_collaborators tc
          ON tc.tree_id = t.tree_id
         AND tc.user_id = %s
        WHERE t.creator_user_id = %s OR tc.user_id = %s
        """,
        (user_id, user_id, user_id),
    )
    total_count = total["count"] if total else 0
    page_info = pagination_context(total_count, page, page_size, 0)
    offset = (page_info["page"] - 1) * page_size
    rows = query_all(
        """
        SELECT
            t.*,
            CASE WHEN t.creator_user_id = %s THEN 'owner' ELSE tc.role END AS current_role,
            COUNT(m.member_id) AS member_count
        FROM family_trees t
        LEFT JOIN tree_collaborators tc
          ON tc.tree_id = t.tree_id
         AND tc.user_id = %s
        LEFT JOIN members m ON m.tree_id = t.tree_id
        WHERE t.creator_user_id = %s OR tc.user_id = %s
        GROUP BY t.tree_id, tc.role
        ORDER BY t.created_at DESC, t.tree_id DESC
        LIMIT %s OFFSET %s
        """,
        (user_id, user_id, user_id, user_id, page_size, offset),
    )
    page_info = pagination_context(total_count, int(page_info["page"]), page_size, len(rows))
    return render_template("trees.html", trees=rows, total=total_count, **page_info)


@app.route("/trees/new", methods=("GET", "POST"))
@login_required
def tree_new():
    if request.method == "POST":
        tree_name = request.form.get("tree_name", "").strip()
        surname = request.form.get("surname", "").strip()
        revision_time = request.form.get("revision_time") or None
        if not tree_name or not surname:
            flash("谱名和姓氏不能为空。", "danger")
        else:
            db = get_db()
            try:
                with db.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO family_trees(tree_name, surname, revision_time, creator_user_id)
                        VALUES (%s, %s, %s, %s)
                        RETURNING tree_id
                        """,
                        (tree_name, surname, revision_time, session["user_id"]),
                    )
                    tree_id = cursor.fetchone()["tree_id"]
                    cursor.execute(
                        """
                        INSERT INTO tree_collaborators(tree_id, user_id, role)
                        VALUES (%s, %s, 'owner')
                        ON CONFLICT (tree_id, user_id) DO UPDATE SET role = EXCLUDED.role
                        """,
                        (tree_id, session["user_id"]),
                    )
                db.commit()
                flash("族谱已创建。", "success")
                return redirect(url_for("members", tree_id=tree_id))
            except psycopg2.Error as exc:
                db.rollback()
                flash(f"创建失败：{exc.diag.message_primary or exc}", "danger")
    return render_template("tree_form.html", tree={})


@app.route("/trees/<int:tree_id>/edit", methods=("GET", "POST"))
@login_required
def tree_edit(tree_id: int):
    try:
        tree = require_tree(tree_id, write=True)
    except PermissionError:
        return redirect(url_for("trees"))

    if request.method == "POST":
        tree_name = request.form.get("tree_name", "").strip()
        surname = request.form.get("surname", "").strip()
        revision_time = request.form.get("revision_time") or None
        if not tree_name or not surname:
            flash("谱名和姓氏不能为空。", "danger")
        else:
            execute(
                """
                UPDATE family_trees
                SET tree_name = %s, surname = %s, revision_time = %s
                WHERE tree_id = %s
                """,
                (tree_name, surname, revision_time, tree_id),
            )
            flash("族谱已更新。", "success")
            return redirect(url_for("trees"))
    return render_template("tree_form.html", tree=tree)


@app.post("/trees/<int:tree_id>/delete")
@login_required
def tree_delete(tree_id: int):
    try:
        require_tree(tree_id, owner=True)
    except PermissionError:
        return redirect(url_for("trees"))
    execute("DELETE FROM family_trees WHERE tree_id = %s", (tree_id,))
    flash("族谱已删除。", "success")
    return redirect(url_for("trees"))


@app.post("/trees/<int:tree_id>/invite")
@login_required
def tree_invite(tree_id: int):
    try:
        require_tree(tree_id, owner=True)
    except PermissionError:
        return redirect(url_for("trees"))

    username = request.form.get("username", "").strip()
    role = request.form.get("role", "editor")
    if role not in {"editor", "viewer"}:
        role = "editor"
    invited = query_one("SELECT user_id FROM users WHERE username = %s", (username,))
    if not invited:
        flash("被邀请用户不存在。", "danger")
    else:
        execute(
            """
            INSERT INTO tree_collaborators(tree_id, user_id, role)
            VALUES (%s, %s, %s)
            ON CONFLICT (tree_id, user_id) DO UPDATE SET role = EXCLUDED.role
            """,
            (tree_id, invited["user_id"], role),
        )
        flash("协作者已保存。", "success")
    return redirect(url_for("trees"))


@app.route("/trees/<int:tree_id>/members")
@login_required
def members(tree_id: int):
    try:
        tree = require_tree(tree_id)
    except PermissionError:
        return redirect(url_for("trees"))

    keyword = request.args.get("q", "").strip()
    page, page_size = get_pagination(default_size=200)

    where_sql = "m.tree_id = %s"
    where_params: list[Any] = [tree_id]
    if keyword:
        where_sql += " AND m.name ILIKE %s"
        where_params.append(f"%{keyword}%")

    total = query_one(f"SELECT COUNT(*) AS count FROM members m WHERE {where_sql}", tuple(where_params))
    total_count = total["count"] if total else 0
    page_info = pagination_context(total_count, page, page_size, 0)
    offset = (page_info["page"] - 1) * page_size

    rows = query_all(
        f"""
        SELECT m.*,
               COUNT(pc.child_id) AS child_count
        FROM members m
        LEFT JOIN parent_child pc ON pc.parent_id = m.member_id
        WHERE {where_sql}
        GROUP BY m.member_id
        ORDER BY m.generation, m.member_id
        LIMIT %s OFFSET %s
        """,
        tuple(where_params + [page_size, offset]),
    )

    tree_total = query_one("SELECT COUNT(*) AS count FROM members WHERE tree_id = %s", (tree_id,))
    page_info = pagination_context(total_count, int(page_info["page"]), page_size, len(rows))
    return render_template(
        "members.html",
        tree=tree,
        members=rows,
        keyword=keyword,
        total=tree_total["count"] if tree_total else 0,
        filtered_total=total_count,
        **page_info,
    )


def existing_relations(member_id: int) -> dict[str, Any]:
    father = query_one(
        "SELECT parent_id FROM parent_child WHERE child_id = %s AND relation_type = 'father'",
        (member_id,),
    )
    mother = query_one(
        "SELECT parent_id FROM parent_child WHERE child_id = %s AND relation_type = 'mother'",
        (member_id,),
    )
    spouse = query_one(
        """
        SELECT
            CASE WHEN spouse1_id = %s THEN spouse2_id ELSE spouse1_id END AS spouse_id,
            marriage_year
        FROM marriages
        WHERE spouse1_id = %s OR spouse2_id = %s
        ORDER BY marriage_id
        LIMIT 1
        """,
        (member_id, member_id, member_id),
    )
    return {
        "father_id": father["parent_id"] if father else "",
        "mother_id": mother["parent_id"] if mother else "",
        "spouse_id": spouse["spouse_id"] if spouse else "",
        "marriage_year": spouse["marriage_year"] if spouse else "",
    }


def save_member_relations(
    cursor,
    tree_id: int,
    member_id: int,
    father_id: int | None,
    mother_id: int | None,
    spouse_id: int | None,
    marriage_year: int | None,
) -> None:
    cursor.execute(
        "DELETE FROM parent_child WHERE child_id = %s AND relation_type IN ('father', 'mother')",
        (member_id,),
    )
    for parent_id, relation_type in ((father_id, "father"), (mother_id, "mother")):
        if parent_id is None:
            continue
        cursor.execute(
            """
            SELECT member_id
            FROM members
            WHERE tree_id = %s AND member_id = %s
            """,
            (tree_id, parent_id),
        )
        if cursor.fetchone() is None:
            raise ValueError(f"{relation_type} ID 不属于当前族谱。")
        cursor.execute(
            """
            INSERT INTO parent_child(parent_id, child_id, relation_type)
            VALUES (%s, %s, %s)
            """,
            (parent_id, member_id, relation_type),
        )

    cursor.execute("DELETE FROM marriages WHERE spouse1_id = %s OR spouse2_id = %s", (member_id, member_id))
    if spouse_id is not None:
        cursor.execute(
            """
            SELECT member_id
            FROM members
            WHERE tree_id = %s AND member_id = %s
            """,
            (tree_id, spouse_id),
        )
        if cursor.fetchone() is None:
            raise ValueError("配偶 ID 不属于当前族谱。")
        spouse1_id, spouse2_id = normalize_pair(member_id, spouse_id)
        cursor.execute(
            """
            INSERT INTO marriages(tree_id, spouse1_id, spouse2_id, marriage_year)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tree_id, spouse1_id, spouse2_id)
            DO UPDATE SET marriage_year = EXCLUDED.marriage_year
            """,
            (tree_id, spouse1_id, spouse2_id, marriage_year),
        )


@app.route("/trees/<int:tree_id>/members/new", methods=("GET", "POST"))
@login_required
def member_new(tree_id: int):
    try:
        tree = require_tree(tree_id, write=True)
    except PermissionError:
        return redirect(url_for("trees"))

    member: dict[str, Any] = {"gender": "M", "generation": 1}
    relations = {"father_id": "", "mother_id": "", "spouse_id": "", "marriage_year": ""}

    if request.method == "POST":
        db = get_db()
        try:
            name = request.form.get("name", "").strip()
            gender = request.form.get("gender", "M")
            birth_year = parse_int(request.form.get("birth_year"), "出生年份", required=True)
            death_year = parse_int(request.form.get("death_year"), "死亡年份")
            generation = parse_int(request.form.get("generation"), "辈分", required=True)
            biography = request.form.get("biography", "").strip()
            father_id = parse_int(request.form.get("father_id"), "父亲 ID")
            mother_id = parse_int(request.form.get("mother_id"), "母亲 ID")
            spouse_id = parse_int(request.form.get("spouse_id"), "配偶 ID")
            marriage_year = parse_int(request.form.get("marriage_year"), "结婚年份")
            if not name:
                raise ValueError("姓名不能为空。")
            if gender not in {"M", "F"}:
                raise ValueError("性别必须为 M 或 F。")

            with db.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO members(tree_id, name, gender, birth_year, death_year, generation, biography)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING member_id
                    """,
                    (tree_id, name, gender, birth_year, death_year, generation, biography),
                )
                member_id = cursor.fetchone()["member_id"]
                save_member_relations(cursor, tree_id, member_id, father_id, mother_id, spouse_id, marriage_year)
            db.commit()
            flash("成员已新增。", "success")
            return redirect(url_for("members", tree_id=tree_id))
        except (ValueError, psycopg2.Error) as exc:
            db.rollback()
            message = exc.diag.message_primary if isinstance(exc, psycopg2.Error) else str(exc)
            flash(f"保存失败：{message}", "danger")
            member = dict(request.form)
            relations = dict(request.form)

    return render_template("member_form.html", tree=tree, member=member, relations=relations)


@app.route("/trees/<int:tree_id>/members/<int:member_id>/edit", methods=("GET", "POST"))
@login_required
def member_edit(tree_id: int, member_id: int):
    try:
        tree = require_tree(tree_id, write=True)
    except PermissionError:
        return redirect(url_for("trees"))

    member = fetch_member(tree_id, member_id)
    if not member:
        flash("成员不存在。", "danger")
        return redirect(url_for("members", tree_id=tree_id))
    relations = existing_relations(member_id)

    if request.method == "POST":
        db = get_db()
        try:
            name = request.form.get("name", "").strip()
            gender = request.form.get("gender", "M")
            birth_year = parse_int(request.form.get("birth_year"), "出生年份", required=True)
            death_year = parse_int(request.form.get("death_year"), "死亡年份")
            generation = parse_int(request.form.get("generation"), "辈分", required=True)
            biography = request.form.get("biography", "").strip()
            father_id = parse_int(request.form.get("father_id"), "父亲 ID")
            mother_id = parse_int(request.form.get("mother_id"), "母亲 ID")
            spouse_id = parse_int(request.form.get("spouse_id"), "配偶 ID")
            marriage_year = parse_int(request.form.get("marriage_year"), "结婚年份")
            if not name:
                raise ValueError("姓名不能为空。")
            if gender not in {"M", "F"}:
                raise ValueError("性别必须为 M 或 F。")

            with db.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE members
                    SET name = %s,
                        gender = %s,
                        birth_year = %s,
                        death_year = %s,
                        generation = %s,
                        biography = %s
                    WHERE tree_id = %s AND member_id = %s
                    """,
                    (name, gender, birth_year, death_year, generation, biography, tree_id, member_id),
                )
                save_member_relations(cursor, tree_id, member_id, father_id, mother_id, spouse_id, marriage_year)
            db.commit()
            flash("成员已更新。", "success")
            return redirect(url_for("members", tree_id=tree_id))
        except (ValueError, psycopg2.Error) as exc:
            db.rollback()
            message = exc.diag.message_primary if isinstance(exc, psycopg2.Error) else str(exc)
            flash(f"保存失败：{message}", "danger")
            member = dict(request.form)
            member["member_id"] = member_id
            relations = dict(request.form)

    return render_template("member_form.html", tree=tree, member=member, relations=relations)


@app.post("/trees/<int:tree_id>/members/<int:member_id>/delete")
@login_required
def member_delete(tree_id: int, member_id: int):
    try:
        require_tree(tree_id, write=True)
    except PermissionError:
        return redirect(url_for("trees"))
    execute("DELETE FROM members WHERE tree_id = %s AND member_id = %s", (tree_id, member_id))
    flash("成员已删除。", "success")
    return redirect(url_for("members", tree_id=tree_id))


@app.route("/trees/<int:tree_id>/preview")
@login_required
def tree_preview(tree_id: int):
    try:
        tree = require_tree(tree_id)
    except PermissionError:
        return redirect(url_for("trees"))

    root_id = parse_int(request.args.get("root_id"), "根成员 ID") if request.args.get("root_id") else None
    depth = min(max(parse_int(request.args.get("depth"), "深度") or 4, 1), 8)
    page, page_size = get_pagination(default_size=200)
    if root_id is None:
        root = query_one(
            """
            SELECT member_id
            FROM members
            WHERE tree_id = %s
            ORDER BY generation, member_id
            LIMIT 1
            """,
            (tree_id,),
        )
        root_id = root["member_id"] if root else None

    rows: list[dict[str, Any]] = []
    has_next = False
    start_row = 0
    end_row = 0
    if root_id:
        descendants_cte = """
            WITH RECURSIVE descendants AS (
                SELECT
                    m.member_id,
                    m.name,
                    m.gender,
                    m.birth_year,
                    m.death_year,
                    m.generation,
                    0 AS depth,
                    ARRAY[m.member_id] AS path
                FROM members m
                WHERE m.tree_id = %s AND m.member_id = %s

                UNION ALL

                SELECT
                    child.member_id,
                    child.name,
                    child.gender,
                    child.birth_year,
                    child.death_year,
                    child.generation,
                    descendants.depth + 1,
                    descendants.path || child.member_id
                FROM descendants
                JOIN parent_child pc ON pc.parent_id = descendants.member_id
                JOIN members child ON child.member_id = pc.child_id
                WHERE child.tree_id = %s
                  AND descendants.depth < %s
                  AND NOT child.member_id = ANY(descendants.path)
            )
        """
        offset = (page - 1) * page_size
        fetched_rows = query_all(
            descendants_cte
            + """
            SELECT *
            FROM descendants
            ORDER BY path
            LIMIT %s OFFSET %s
            """,
            (tree_id, root_id, tree_id, depth, page_size + 1, offset),
        )
        has_next = len(fetched_rows) > page_size
        rows = fetched_rows[:page_size]
        start_row = offset + 1 if rows else 0
        end_row = offset + len(rows)
    return render_template(
        "tree_preview.html",
        tree=tree,
        rows=rows,
        root_id=root_id,
        depth=depth,
        page=page,
        page_size=page_size,
        page_size_options=PAGE_SIZE_OPTIONS,
        start_row=start_row,
        end_row=end_row,
        has_next=has_next,
    )


@app.route("/trees/<int:tree_id>/ancestors", methods=("GET", "POST"))
@login_required
def ancestors(tree_id: int):
    try:
        tree = require_tree(tree_id)
    except PermissionError:
        return redirect(url_for("trees"))

    member_id = parse_int(request.values.get("member_id"), "成员 ID") if request.values.get("member_id") else None
    page, page_size = get_pagination(default_size=100)
    rows: list[dict[str, Any]] = []
    target = None
    has_next = False
    start_row = 0
    end_row = 0
    if member_id:
        target = fetch_member(tree_id, member_id)
        if target:
            ancestors_cte = """
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
                    WHERE pc.child_id = %s AND parent.tree_id = %s

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
                    WHERE grand_parent.tree_id = %s
                      AND NOT grand_parent.member_id = ANY(ancestors.path)
                )
            """
            offset = (page - 1) * page_size
            fetched_rows = query_all(
                ancestors_cte
                + """
                SELECT *
                FROM ancestors
                LIMIT %s OFFSET %s
                """,
                (member_id, tree_id, tree_id, page_size + 1, offset),
            )
            has_next = len(fetched_rows) > page_size
            rows = fetched_rows[:page_size]
            start_row = offset + 1 if rows else 0
            end_row = offset + len(rows)
        else:
            flash("成员不存在或不属于当前族谱。", "danger")
    return render_template(
        "ancestors.html",
        tree=tree,
        member_id=member_id,
        target=target,
        rows=rows,
        page=page,
        page_size=page_size,
        page_size_options=PAGE_SIZE_OPTIONS,
        start_row=start_row,
        end_row=end_row,
        has_next=has_next,
    )


@app.route("/trees/<int:tree_id>/relationship", methods=("GET", "POST"))
@login_required
def relationship(tree_id: int):
    try:
        tree = require_tree(tree_id)
    except PermissionError:
        return redirect(url_for("trees"))

    member_a_id = parse_int(request.values.get("member_a_id"), "成员 A ID") if request.values.get("member_a_id") else None
    member_b_id = parse_int(request.values.get("member_b_id"), "成员 B ID") if request.values.get("member_b_id") else None
    result = None
    path_members: list[dict[str, Any]] = []
    target_a = fetch_member(tree_id, member_a_id) if member_a_id else None
    target_b = fetch_member(tree_id, member_b_id) if member_b_id else None

    if member_a_id and member_b_id:
        if not target_a or not target_b:
            flash("两个成员 ID 都必须属于当前族谱。", "danger")
        else:
            result = query_one(
                """
                WITH RECURSIVE
                direct_spouse AS (
                    SELECT
                        ARRAY[%s::BIGINT, %s::BIGINT] AS path,
                        ARRAY['spouse']::TEXT[] AS edge_labels,
                        1 AS depth
                    FROM marriages ma
                    WHERE ma.tree_id = %s
                      AND ma.spouse1_id = LEAST(%s::BIGINT, %s::BIGINT)
                      AND ma.spouse2_id = GREATEST(%s::BIGINT, %s::BIGINT)
                ),
                up_from_a AS (
                    SELECT
                        %s::BIGINT AS current_id,
                        ARRAY[%s::BIGINT] AS path,
                        0 AS depth

                    UNION ALL

                    SELECT
                        pc.parent_id,
                        up_from_a.path || pc.parent_id,
                        up_from_a.depth + 1
                    FROM up_from_a
                    JOIN parent_child pc ON pc.child_id = up_from_a.current_id
                    JOIN members parent ON parent.member_id = pc.parent_id
                    WHERE up_from_a.depth < 40
                      AND parent.tree_id = %s
                      AND NOT pc.parent_id = ANY(up_from_a.path)
                ),
                up_from_b AS (
                    SELECT
                        %s::BIGINT AS current_id,
                        ARRAY[%s::BIGINT] AS path,
                        0 AS depth

                    UNION ALL

                    SELECT
                        pc.parent_id,
                        up_from_b.path || pc.parent_id,
                        up_from_b.depth + 1
                    FROM up_from_b
                    JOIN parent_child pc ON pc.child_id = up_from_b.current_id
                    JOIN members parent ON parent.member_id = pc.parent_id
                    WHERE up_from_b.depth < 40
                      AND parent.tree_id = %s
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
                LIMIT 1
                """,
                (
                    member_a_id,
                    member_b_id,
                    tree_id,
                    member_a_id,
                    member_b_id,
                    member_a_id,
                    member_b_id,
                    member_a_id,
                    member_a_id,
                    tree_id,
                    member_b_id,
                    member_b_id,
                    tree_id,
                ),
            )
            if result:
                member_rows = query_all(
                    """
                    SELECT member_id, name, gender, generation
                    FROM members
                    WHERE tree_id = %s AND member_id = ANY(%s)
                    """,
                    (tree_id, result["path"]),
                )
                member_map = {row["member_id"]: row for row in member_rows}
                path_members = [member_map[item] for item in result["path"] if item in member_map]
            else:
                flash("在 12 步以内没有找到亲缘通路。", "warning")

    return render_template(
        "relationship.html",
        tree=tree,
        member_a_id=member_a_id,
        member_b_id=member_b_id,
        target_a=target_a,
        target_b=target_b,
        result=result,
        path_members=path_members,
    )


if __name__ == "__main__":
    app.run(debug=True)
