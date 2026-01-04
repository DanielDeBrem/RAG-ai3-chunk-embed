#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/Projects/RAG-ai3-chunk-embed"
cd "$ROOT"

BACKUP_DIR="$ROOT/backup_datafactory_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Backup bestaande files als ze er zijn
[ -f main.py ] && cp main.py "$BACKUP_DIR/main.py"
[ -f models.py ] && cp models.py "$BACKUP_DIR/models.py"

echo "Backups opgeslagen in: $BACKUP_DIR"

#######################################
# models.py - datamodellen AI-3 datafactory
#######################################
cat > models.py << 'PY'
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
PY

#######################################
# main.py - AI-3 DataFactory service (9000)
#######################################
cat > main.py << 'PY'
from __future__ import annotations

from typing import List
import math

import requests
from fastapi import FastAPI, HTTPException
from models import (
    IngestRequest,
    IngestResponse,
    Chunk,
    SearchRequest,
    SearchResponse,
    SearchHit,
)

# Gebruik de bestaande embedding_service (we gaan er vanuit dat die embed_texts(List[str]) -> List[List[float]] heeft)
from embedding_service import embed_texts

app = FastAPI(title="AI-3 DataFactory", version="0.1.0")

# Heel simpele in-memory “vector store”
DOC_STORE: List[Chunk] = []

ANALYZER_URL = "http://localhost:9100/analyze"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ai3-datafactory",
        "documents": len({c.document_id for c in DOC_STORE}),
        "chunks": len(DOC_STORE),
    }


def _simple_chunk(text: str, max_chars: int = 800) -> List[str]:
    """
    Hele simpele chunker: splitst op zinnen/regels en pakt bundels tot max_chars.
    Later kun je dit vervangen door een slimme, document_type-specifieke chunker.
    """
    # split eerst grof op regels
    import re

    parts = re.split(r"(\n+|[.!?]+ )", text)
    pieces: List[str] = []
    current = ""

    for part in parts:
        if not part:
            continue
        if len(current) + len(part) <= max_chars:
            current += part
        else:
            if current.strip():
                pieces.append(current.strip())
            current = part
    if current.strip():
        pieces.append(current.strip())

    # fallback: als het leeg is
    if not pieces:
        pieces = [text.strip()]
    return pieces


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest) -> IngestResponse:
    # 1) Analyzer aanroepen op AI-3 (9100)
    try:
        resp = requests.post(
            ANALYZER_URL,
            json={
                "document": req.text,
                "filename": req.filename,
                "mime_type": req.mime_type,
            },
            timeout=120,
        )
        resp.raise_for_status()
        analysis = resp.json().get("analysis", {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"analyze_failed: {e}")

    document_type = analysis.get("document_type", "generic_doc")

    # 2) Chunken
    chunks_text = _simple_chunk(req.text)
    if not chunks_text:
        raise HTTPException(status_code=400, detail="no_chunks_generated")

    # 3) Embedden via bestaande embedding_service
    try:
        embeddings = embed_texts(chunks_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"embed_failed: {e}")

    if not embeddings or len(embeddings) != len(chunks_text):
        raise HTTPException(status_code=500, detail="embedding_mismatch")

    # 4) Opslaan in in-memory store
    document_id = f"{req.tenant_id}:{req.project_id}:{len({c.document_id for c in DOC_STORE})}"

    for idx, (chunk_text, vec) in enumerate(zip(chunks_text, embeddings)):
        chunk = Chunk(
            tenant_id=req.tenant_id,
            project_id=req.project_id,
            document_id=document_id,
            chunk_id=f"{document_id}:{idx}",
            text=chunk_text,
            embedding=vec,
            metadata={
                "filename": req.filename,
                "mime_type": req.mime_type or "",
                "document_type": document_type,
            },
        )
        DOC_STORE.append(chunk)

    return IngestResponse(
        status="ok",
        document_id=document_id,
        chunk_count=len(chunks_text),
    )


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    # Query embedden
    try:
        query_vecs = embed_texts([req.query])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"embed_failed: {e}")

    if not query_vecs:
        raise HTTPException(status_code=500, detail="no_query_vector")

    qv = query_vecs[0]

    # Filter op tenant/project en cosine similarity
    candidates = [
        c for c in DOC_STORE
        if c.tenant_id == req.tenant_id and c.project_id == req.project_id
    ]

    scored: List[SearchHit] = []
    for c in candidates:
        score = _cosine(qv, c.embedding)
        scored.append(
            SearchHit(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                text=c.text,
                score=score,
                metadata=c.metadata,
            )
        )

    scored.sort(key=lambda h: h.score, reverse=True)
    top = scored[: req.top_k]

    return SearchResponse(hits=top)
PY

echo "AI-3 datafactory (main.py + models.py) opnieuw geschreven."
