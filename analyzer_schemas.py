from __future__ import annotations

from typing import List, Dict, Optional

from pydantic import BaseModel, Field


class DocumentAnalysis(BaseModel):
    document_type: str
    mime_type: Optional[str] = None
    language: Optional[str] = None
    page_count: Optional[int] = None

    has_tables: bool = False
    has_images: bool = False

    main_entities: List[str] = Field(default_factory=list)
    main_topics: List[str] = Field(default_factory=list)

    # hoe we verder moeten chunken / embedden
    suggested_chunk_strategy: str
    suggested_embed_model: str

    # extra hints/flags/metadata
    extra: Dict[str, str] = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    document: str
    filename: Optional[str] = None
    mime_type: Optional[str] = None


class AnalyzeResponse(BaseModel):
    analysis: DocumentAnalysis


class HealthResponse(BaseModel):
    status: str
    service: str
