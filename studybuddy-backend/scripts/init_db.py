"""Initialize the current ORM schema in an EMPTY database only.

Create the database and grant a dedicated user access first. This is intentionally
not a migration or reset command: any existing table makes it refuse to run.
"""
from sqlalchemy import inspect

import app.models  # noqa: F401 - register the shared application models
import app.models.exam_batch  # noqa: F401
import app.models.note  # noqa: F401
from app.database import Base, engine


def main() -> None:
    if inspect(engine).get_table_names():
        raise SystemExit("Refusing initialization: database already contains tables.")
    Base.metadata.create_all(engine)
    print(f"Initialized {len(inspect(engine).get_table_names())} tables. No user records created.")


if __name__ == "__main__":
    main()
