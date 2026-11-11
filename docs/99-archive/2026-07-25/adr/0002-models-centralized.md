# ADR-0002: ORM 模型集中 app/models，不进 feature

- 状态：accepted
- 日期：2026-07-19
- 关联：`archive/2026-07-22/设计/后端模块化架构.md` §3、§4.1

## 背景

项目用 `sql/001-020_*.sql` 增量脚本 + `scripts/run_ddl.py` 执行器维护表结构（`scripts/ensure_*.py` 为补充）。表结构、ORM model、SQL 脚本三者靠编号人工对应，没有 Alembic 自动发现。

## 决策

ORM 模型继续集中在 `app/models/`，**不**放进 `features/<模块>/models.py`。`features/<模块>/` 只放 router / service / schemas。

## 放弃的方案

- **model 进 feature**（`features/exams/models.py`、`features/plans/models.py`）：表 ↔ model ↔ SQL 脚本三方分散在不同 feature 目录，改表时要跨目录找对应 SQL 脚本，人工对应更易错。

## 影响

- feature 目录只有 router/service/schemas，不含表模型。
- `app/models/` 保持集中，建表脚本和 model 的对应关系不变。
- 迁移成本最小：迁 feature 不碰 model 层。
