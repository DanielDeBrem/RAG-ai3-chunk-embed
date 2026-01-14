"""
Database models for persistent RAG storage.

Schema:
- docs: Document metadata
- chunks: Chunk text + embeddings + FAISS mapping
- indices: FAISS index file tracking
- jobs: Persistent job queue
"""
import json
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import (
    create_engine, Column, String, Integer, Text, DateTime,
    Boolean, ForeignKey, Index as DBIndex, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Base = declarative_base()


class Document(Base):
    """Document metadata table."""
    __tablename__ = 'docs'
    
    doc_id = Column(String(512), primary_key=True)
    tenant_id = Column(String(128), nullable=False, index=True)
    namespace = Column(String(128), nullable=False, index=True)
    source = Column(String(512), nullable=True)
    doc_hash = Column(String(64), nullable=False)  # SHA256 of content
    meta_json = Column(Text, nullable=True)  # JSON serialized metadata
    policy_id = Column(String(128), nullable=True)
    embedding_model_id = Column(String(128), nullable=False)
    embedding_version = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True, index=True)
    
    # Relationships
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
    
    # Composite indexes for common queries
    __table_args__ = (
        DBIndex('idx_tenant_namespace', 'tenant_id', 'namespace'),
        DBIndex('idx_tenant_namespace_deleted', 'tenant_id', 'namespace', 'deleted_at'),
        DBIndex('idx_doc_hash', 'doc_hash'),
    )
    
    def get_metadata(self) -> Dict[str, Any]:
        """Parse JSON metadata."""
        if not self.meta_json:
            return {}
        try:
            return json.loads(self.meta_json)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    def set_metadata(self, meta: Dict[str, Any]):
        """Serialize metadata to JSON."""
        self.meta_json = json.dumps(meta) if meta else None


class Chunk(Base):
    """Chunk table with FAISS mapping."""
    __tablename__ = 'chunks'
    
    chunk_id = Column(String(512), primary_key=True)
    doc_id = Column(String(512), ForeignKey('docs.doc_id'), nullable=False, index=True)
    tenant_id = Column(String(128), nullable=False, index=True)
    namespace = Column(String(128), nullable=False, index=True)
    chunk_hash = Column(String(64), nullable=False, index=True)  # SHA256 of text
    text = Column(Text, nullable=False)  # Raw chunk text
    embed_text = Column(Text, nullable=True)  # Enriched text (optional)
    offset_start = Column(Integer, nullable=True)
    offset_end = Column(Integer, nullable=True)
    meta_json = Column(Text, nullable=True)  # JSON serialized metadata
    policy_id = Column(String(128), nullable=True)
    embedding_model_id = Column(String(128), nullable=False)
    embedding_version = Column(String(64), nullable=False)
    faiss_id = Column(Integer, nullable=True, index=True)  # FAISS internal ID
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True, index=True)
    
    # Relationships
    document = relationship("Document", back_populates="chunks")
    
    # Composite indexes for common queries
    __table_args__ = (
        DBIndex('idx_tenant_namespace_chunks', 'tenant_id', 'namespace'),
        DBIndex('idx_tenant_namespace_deleted_chunks', 'tenant_id', 'namespace', 'deleted_at'),
        DBIndex('idx_chunk_hash', 'chunk_hash'),
        DBIndex('idx_faiss_id', 'faiss_id'),
    )
    
    def get_metadata(self) -> Dict[str, Any]:
        """Parse JSON metadata."""
        if not self.meta_json:
            return {}
        try:
            return json.loads(self.meta_json)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    def set_metadata(self, meta: Dict[str, Any]):
        """Serialize metadata to JSON."""
        self.meta_json = json.dumps(meta) if meta else None


class IndexMetadata(Base):
    """FAISS index file tracking."""
    __tablename__ = 'indices'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(128), nullable=False)
    namespace = Column(String(128), nullable=False)
    embedding_version = Column(String(64), nullable=False)
    faiss_path = Column(String(512), nullable=False)  # Path to FAISS index file
    ntotal = Column(Integer, default=0, nullable=False)  # Number of vectors
    dimension = Column(Integer, nullable=False)  # Embedding dimension
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    dirty = Column(Boolean, default=False, nullable=False)  # Needs rebuild
    
    # Unique constraint on (tenant_id, namespace, embedding_version)
    __table_args__ = (
        UniqueConstraint('tenant_id', 'namespace', 'embedding_version', name='uq_index_key'),
        DBIndex('idx_dirty', 'dirty'),
    )


class Job(Base):
    """Persistent job queue."""
    __tablename__ = 'jobs'
    
    job_id = Column(String(64), primary_key=True)
    type = Column(String(64), nullable=False, index=True)  # ingest_docs, rebuild_index
    payload_json = Column(Text, nullable=False)  # JSON serialized job data
    status = Column(String(32), default='pending', nullable=False, index=True)  # pending, running, completed, failed
    progress = Column(Integer, default=0, nullable=False)  # 0-100
    error = Column(Text, nullable=True)  # Error message if failed
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    __table_args__ = (
        DBIndex('idx_status', 'status'),
        DBIndex('idx_type_status', 'type', 'status'),
    )
    
    def get_payload(self) -> Dict[str, Any]:
        """Parse JSON payload."""
        try:
            return json.loads(self.payload_json)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    def set_payload(self, payload: Dict[str, Any]):
        """Serialize payload to JSON."""
        self.payload_json = json.dumps(payload)


# Database engine and session factory (will be initialized in db.py)
engine = None
SessionLocal = None


def init_db(database_url: str = "sqlite:///./ai3_rag.db"):
    """Initialize database engine and create tables."""
    global engine, SessionLocal
    
    # SQLite-specific configuration for better concurrency
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {
            "check_same_thread": False,
            "timeout": 30.0,  # Wait up to 30s for lock
        }
    
    engine = create_engine(
        database_url,
        connect_args=connect_args,
        echo=False,  # Set to True for SQL logging
        pool_pre_ping=True,  # Verify connections before using
    )
    
    # Enable WAL mode for SQLite (better concurrency)
    if database_url.startswith("sqlite"):
        from sqlalchemy import event
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")  # 30s timeout
            cursor.close()
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    # Create session factory
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    return engine


def get_session():
    """Get a new database session."""
    if SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return SessionLocal()
