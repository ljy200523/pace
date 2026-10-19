from collections.abc import Generator
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.engine import make_url

from app.config import settings


class Base(DeclarativeBase):
    pass


database_url = make_url(settings.database_url)
if database_url.drivername in {"postgres", "postgresql"}:
    database_url = database_url.set(drivername="postgresql+psycopg")

is_sqlite = database_url.drivername.startswith("sqlite")
is_vercel = os.getenv("VERCEL") == "1"
is_supabase = bool(database_url.host and (database_url.host.endswith(".supabase.co") or database_url.host.endswith(".pooler.supabase.com")))
connect_args = {"check_same_thread": False} if is_sqlite else ({"sslmode": "require"} if is_supabase else {})
if database_url.port == 6543:
    # Supabase's transaction pooler cannot retain prepared statements between transactions.
    connect_args["prepare_threshold"] = None

# Vercel invocations and Supabase transaction-pooler connections should not
# retain SQLAlchemy's per-process connection pool across serverless requests.
use_null_pool = is_vercel or database_url.port == 6543
engine_options = {"connect_args": connect_args, "pool_pre_ping": not use_null_pool}
if use_null_pool:
    engine_options["poolclass"] = NullPool
engine = create_engine(database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
