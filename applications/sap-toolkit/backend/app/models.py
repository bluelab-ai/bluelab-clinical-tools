from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    sap_filename = Column(String(500), nullable=False)
    crf_filename = Column(String(500), nullable=True)
    sap_path = Column(String(1000), nullable=False)
    crf_path = Column(String(1000), nullable=True)
    output_dir = Column(String(1000), nullable=True)
    status = Column(String(20), default="pending")  # pending, running, completed, failed
    phase = Column(String(20), default="pending")  # pending, phase1, catalog, phase2, completed
    tables_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
