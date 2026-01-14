from __future__ import annotations

from typing import List, Dict, Optional
from pydantic import BaseModel


class IngestRequest(BaseModel):
    tenant_id: str
    project_id: str
    user_id: Optional[str] = None

    filename: str
    mime_type: Optional[str] = None
    text: str


class IngestResponse(BaseModel):
    status: str
    document_id: str
    chunk_count: int


class Chunk(BaseModel):
    tenant_id: str
    project_id: str
    document_id: str
    chunk_id: str

    text: str
    embedding: List[float]
    metadata: Dict[str, str] = {}


class SearchRequest(BaseModel):
    tenant_id: str
    project_id: str
    query: str
    top_k: int = 5


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    score: float
    metadata: Dict[str, str] = {}


class SearchResponse(BaseModel):
    hits: List[SearchHit]
