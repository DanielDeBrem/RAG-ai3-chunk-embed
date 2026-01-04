# rerank_schemas.py
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class RerankItem(BaseModel):
    id: str
    text: str
    metadata: Dict[str, str] = Field(default_factory=dict)


class RerankRequest(BaseModel):
    query: str
    items: List[RerankItem]
    top_k: int = 10


class RerankedItem(BaseModel):
    id: str
    text: str
    score: float
    metadata: Dict[str, str] = Field(default_factory=dict)


class RerankResponse(BaseModel):
    items: List[RerankedItem]
