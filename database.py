from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

DATABASE_URL = "sqlite:///./event.db"

# For SQLite in a multi-client setup we prefer to use NullPool so connections are
# not held open by long-lived sessions and we avoid QueuePool timeouts under load.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()
