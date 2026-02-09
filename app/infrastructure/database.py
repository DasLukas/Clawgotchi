from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.models import Base


class Database:
    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, echo=False, future=True, connect_args=connect_args)
        self.session_factory = sessionmaker(bind=self.engine, class_=Session, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)
