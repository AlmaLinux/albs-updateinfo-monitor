from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from updateinfo_monitor.config import settings

engine = create_engine(
    settings.pg_dsn,
)
Session = sessionmaker(engine)


@contextmanager
def get_session():
    with Session() as session:
        try:
            yield session
        finally:
            session.close()
