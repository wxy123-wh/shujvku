# 寻根溯源族谱管理系统

这是按 `计划.md` 实现的最小可演示版本，包含 PostgreSQL 表结构、索引、核心查询、CSV 数据生成脚本和 Flask 图形化界面。

## 目录

```text
genealogy_system/
  app.py
  requirements.txt
  sql/
    01_schema.sql
    02_indexes.sql
    03_queries.sql
    04_import.sql
    05_performance_compare.sql
  scripts/
    generate_data.py
    check_data.py
  data/
  templates/
  static/
  screenshots/
  report/
```

## 快速运行

1. 安装依赖：

```powershell
cd D:\xuexi\数据库\genealogy_system
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. 创建数据库并建表：

```powershell
createdb -U postgres genealogy_db
psql -U postgres -d genealogy_db -f sql/01_schema.sql
```

3. 生成并导入模拟数据：

```powershell
python scripts/generate_data.py
python scripts/check_data.py
psql -U postgres -d genealogy_db -f sql/04_import.sql
psql -U postgres -d genealogy_db -f sql/02_indexes.sql
```

4. 启动 Flask：

```powershell
Copy-Item .env.example .env
# 编辑 .env 里的 DATABASE_URL 和 FLASK_SECRET_KEY
python app.py
```

浏览器打开 `http://127.0.0.1:5000`。

## 演示账号

生成数据脚本会创建 `user1` 到 `user6`，密码都是 `123456`。

## 核心功能

- 用户注册、登录、退出
- 登录后只显示自己创建或受邀协作的族谱
- Dashboard 显示可见族谱总人数、男女比例
- 族谱增删改查、邀请协作者
- 成员增删改查、姓名模糊搜索
- 树形预览某个成员的后代分支
- 递归查询某个成员的祖先
- 查询两名成员之间的亲缘通路
- PostgreSQL 递归 CTE 核心查询与索引脚本

## 性能对比

按实验要求做“无索引 / 有索引”的四代查询对比时，可以使用：

```powershell
psql -U postgres -d genealogy_db
\set ancestor_id 1
\i sql/05_performance_compare.sql
```

流程建议：

1. 只执行 `sql/01_schema.sql` 和 `sql/04_import.sql` 后运行一次 `05_performance_compare.sql`，截图无索引结果。
2. 执行 `sql/02_indexes.sql`。
3. 再运行同一条 `05_performance_compare.sql`，截图有索引结果。

## 数据规模验证 SQL

```sql
SELECT COUNT(*) FROM members;
SELECT tree_id, COUNT(*) FROM members GROUP BY tree_id ORDER BY COUNT(*) DESC;
SELECT tree_id, MAX(generation) FROM members GROUP BY tree_id ORDER BY MAX(generation) DESC;
```

## 数据库导出

```powershell
pg_dump -U postgres -d genealogy_db -f genealogy_backup.sql
```

导出的 `genealogy_backup.sql` 可以放入提交包或报告附件。
