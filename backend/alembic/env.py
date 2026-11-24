from alembic import context
from app.core.config import get_settings
from app.core.db import Base, make_engine
import app.models  # noqa: F401

target_metadata = Base.metadata


def run_migrations_online():
    engine = make_engine(get_settings().database_url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
