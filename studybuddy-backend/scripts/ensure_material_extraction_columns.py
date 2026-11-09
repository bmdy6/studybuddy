import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal

# 已存在但类型需升级的列（旧库 TEXT → MEDIUMTEXT，教材整本 Markdown 超出 64KB）
MODIFY_COLUMNS = {
    "raw_text": "MEDIUMTEXT NULL",
    "recognized_markdown": "MEDIUMTEXT NULL",
    "confirmed_markdown": "MEDIUMTEXT NULL",
}


def _column_types(db) -> dict[str, str]:
    return {row[0]: row[1].lower() for row in db.execute(text("SHOW COLUMNS FROM materials")).all()}


COLUMNS = {
    "raw_text": "TEXT NULL",
    "recognized_markdown": "TEXT NULL",
    "confirmed_markdown": "TEXT NULL",
    "summary": "VARCHAR(512) NULL",
    "content_type": "VARCHAR(64) NULL",
    "recognition_status": "VARCHAR(32) NOT NULL DEFAULT 'pending'",
    "recognition_provider": "VARCHAR(32) NULL",
    "recognition_confidence": "VARCHAR(16) NULL",
    "uncertain_points": "JSON NULL",
    "recognized_at": "DATETIME NULL",
    "confirmed_at": "DATETIME NULL",
    # PR-06 素材归属与双层去重字段
    "student_id": "BIGINT NULL",
    "file_sha256": "VARCHAR(64) NULL",
    "content_fingerprint": "VARCHAR(64) NULL",
    "auto_ready": "TINYINT(1) NOT NULL DEFAULT 0",
    "duplicate_of_material_id": "BIGINT NULL",
}

# 普通索引（幂等添加）。不建唯一约束：file_sha256 按“归属范围”判断。
INDEXES = {
    "idx_material_student": "student_id",
    "idx_material_sha": "file_sha256",
    "idx_material_fingerprint": "content_fingerprint",
}

# 外键约束（幂等添加，MySQL 5.7 兼容）。
FOREIGN_KEYS = {
    "fk_materials_student": "FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE SET NULL",
    "fk_materials_duplicate_of": "FOREIGN KEY (duplicate_of_material_id) REFERENCES materials(id) ON DELETE SET NULL",
}


def _existing_columns(db) -> set[str]:
    return {row[0] for row in db.execute(text("SHOW COLUMNS FROM materials")).all()}


def _existing_index_names(db) -> set[str]:
    # SHOW INDEX 每个索引每个列返回一行，Key_name 字段名固定。
    return {row._mapping["Key_name"] for row in db.execute(text("SHOW INDEX FROM materials")).all()}


def _existing_fk_names(db) -> set[str]:
    rows = db.execute(
        text(
            "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'materials' AND CONSTRAINT_TYPE = 'FOREIGN KEY'"
        )
    ).all()
    return {row[0] for row in rows}


def main() -> None:
    with SessionLocal() as db:
        existing_cols = _existing_columns(db)
        added: list[str] = []
        for name, ddl in COLUMNS.items():
            if name in existing_cols:
                continue
            db.execute(text(f"ALTER TABLE materials ADD COLUMN {name} {ddl}"))
            added.append(name)
        db.commit()

        # 旧库 TEXT 列升级为 MEDIUMTEXT（幂等：已是 mediumtext 则跳过）
        col_types = _column_types(db)
        modified: list[str] = []
        for name, ddl in MODIFY_COLUMNS.items():
            if name in col_types and "mediumtext" not in col_types[name]:
                db.execute(text(f"ALTER TABLE materials MODIFY COLUMN {name} {ddl}"))
                modified.append(name)
        db.commit()

        existing_indexes = _existing_index_names(db)
        added_indexes: list[str] = []
        for name, col in INDEXES.items():
            if name in existing_indexes:
                continue
            db.execute(text(f"ALTER TABLE materials ADD INDEX {name} ({col})"))
            added_indexes.append(name)
        db.commit()

        existing_fks = _existing_fk_names(db)
        added_fks: list[str] = []
        for name, ddl in FOREIGN_KEYS.items():
            if name in existing_fks:
                continue
            try:
                db.execute(text(f"ALTER TABLE materials ADD CONSTRAINT {name} {ddl}"))
                added_fks.append(name)
            except Exception as e:  # noqa: BLE001 - FK 已存在或列缺失时不阻断（幂等）
                print(f"跳过外键 {name}：{e}")
        db.commit()

    messages = []
    if added:
        messages.append("已补充 materials 字段：" + "、".join(added))
    if modified:
        messages.append("已升级 materials 大文本列：" + "、".join(modified))
    if added_indexes:
        messages.append("已补充 materials 索引：" + "、".join(added_indexes))
    if added_fks:
        messages.append("已补充 materials 外键：" + "、".join(added_fks))
    print("\n".join(messages) if messages else "materials 字段、索引、外键已存在，无需修改")


if __name__ == "__main__":
    main()
