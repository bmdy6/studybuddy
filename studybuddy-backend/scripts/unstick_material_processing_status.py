"""把卡在 processing 的素材翻成 pending，让懒识别在首次 read_material 时重新触发。

背景：旧流程上传时同步识别，worker 超时会把 recognition_status='processing' 永久留在库里，
前端渲染成「识别中」卡死。新流程改为懒识别（read_material 首次读取时触发 ensure_extraction），
processing 只在识别进行中瞬时存在。本脚本一次性回收存量卡死的 processing -> pending。

幂等：没有 processing 记录时 rowcount=0，可重复执行。
"""

import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import SessionLocal


def main() -> None:
    with SessionLocal() as db:
        result = db.execute(
            text(
                "UPDATE materials SET recognition_status = 'pending' "
                "WHERE recognition_status = 'processing'"
            )
        )
        db.commit()
        count = result.rowcount
        if count:
            print(f"已把 {count} 个卡在 processing 的素材翻成 pending，懒识别会在首次读取时重新触发")
        else:
            print("没有卡在 processing 的素材，无需修改")


if __name__ == "__main__":
    main()
