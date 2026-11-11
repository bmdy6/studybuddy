"""一次性迁移：历史 draft 笔记置 confirmed。

以前 save_note 直接落 draft 但没有对话确认环节，存量 draft 实为用户已认可的笔记。
现在引入「对话确认才转 confirmed」后，跑此脚本把存量 draft 一次性转 confirmed，
让它们进 AI 记忆/每日记录/笔记列表（不再显示待确认）。

用法：python scripts/migrate_draft_notes_to_confirmed.py
"""

import json
import sys

from app.database import SessionLocal
from app.features.note import service as note_service


def main() -> int:
    db = SessionLocal()
    try:
        count = note_service.confirm_all_draft_notes(db)
        print(json.dumps({"migrated": count}, ensure_ascii=False))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
