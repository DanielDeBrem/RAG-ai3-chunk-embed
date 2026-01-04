#!/usr/bin/env bash
set -e

cd ~/Projects/RAG-ai3-chunk-embed

BACKUP_DIR="backup_datafactory_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -f datafactory_app.py ]; then
  echo "[*] Backup bestaande datafactory_app.py -> $BACKUP_DIR/datafactory_app.py"
  mv datafactory_app.py "$BACKUP_DIR/datafactory_app.py"
fi

cat > datafactory_app.py << 'PY'
from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, Field

from embedding_service import embed_texts


app = FastAPI(
    title="AI-3 DataFactory",
    version="0.3.0",
)


# ---------- Modellen voor responses ----------

class IngestResponse(BaseModel):
    status: str
    document_id: str
    chunk_count: int


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
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    hits: List[SearchHit]


class HealthResponse(BaseModel):
    status: str
    service: str
    documents: int
    chunks: int


class StoredChunk(BaseModel):
    tenant_id: str
    project_id: str
    doc_id: str
    chunk_id: str
    text: str
    embedding: List[float]
    metadata: Dict[str, Any] = Field(default_factory=dict)


# simpele in-memory store
VECTOR_STORE: List[StoredChunk] = []


# ---------- helpers ----------

def _cosine(a: List[float], b: List[float]) -> float:
    import math

    if len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


# ---------- endpoints ----------

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    doc_ids: Set[str] = {c.doc_id for c in VECTOR_STORE}
    return HealthResponse(
        status="ok",
        service="ai3-datafactory",
        documents=len(doc_ids),
        chunks=len(VECTOR_STORE),
    )


@app.post("/ingest", response_model=IngestResponse)
def ingest(payload: Dict[str, Any] = Body(...)) -> IngestResponse:
    """
    Ingest één documenttekst als één chunk.

    LET OP:
    - We gebruiken hier GEEN Pydantic-body-model meer.
    - Alles wat AI-4 meestuurt wordt uit deze dict gevist.
    - Onbekende/extra velden geven nooit meer 422.
    """
    try:
        # Hard defensief parsen, alles optioneel
        tenant_id = str(payload.get("tenant_id") or "default-tenant")
        project_id = str(payload.get("project_id") or "default-project")
        user_id = str(payload.get("user_id") or "unknown-user")
        filename = str(payload.get("filename") or "unknown")
        text = str(payload.get("text") or "").strip()

        if not text:
            raise HTTPException(status_code=400, detail="empty text")

        mime_type = payload.get("mime_type")
        document_type = payload.get("document_type")
        metadata_raw = payload.get("metadata") or {}
        analysis = payload.get("analysis")

        # metadata recht trekken
        meta: Dict[str, Any] = {}
        if isinstance(metadata_raw, dict):
            meta.update(metadata_raw)
        else:
            meta["_raw_metadata"] = str(metadata_raw)

        meta.update(
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "user_id": user_id,
                "filename": filename,
                "mime_type": mime_type,
            }
        )

        if document_type:
            meta["document_type"] = document_type
        if analysis is not None:
            meta["analysis"] = analysis

        doc_id = f"{tenant_id}:{project_id}:{filename}"

        # 1) embedding via jouw embedding_service
        vec = embed_texts([text])[0]

        chunk = StoredChunk(
            tenant_id=tenant_id,
            project_id=project_id,
            doc_id=doc_id,
            chunk_id=f"{doc_id}#0",
            text=text,
            embedding=vec,
            metadata=meta,
        )
        VECTOR_STORE.append(chunk)

        return IngestResponse(
            status="ok",
            document_id=doc_id,
            chunk_count=1,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"embed_failed: {e}")


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    """
    Eenvoudige cosine-similarity search in de in-memory store.
    """
    try:
        q_vec = embed_texts([req.query])[0]

        candidates = [
            c
            for c in VECTOR_STORE
            if c.tenant_id == req.tenant_id and c.project_id == req.project_id
        ]

        scored: List[Tuple[float, StoredChunk]] = [
            (_cosine(q_vec, c.embedding), c) for c in candidates
        ]
        scored.sort(key=lambda t: t[0], reverse=True)

        top_k = max(1, req.top_k)
        top = scored[:top_k]

        hits = [
            SearchHit(
                chunk_id=c.chunk_id,
                document_id=c.doc_id,
                text=c.text,
                score=score,
                metadata=c.metadata,
            )
            for score, c in top
        ]
        return SearchResponse(hits=hits)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"search_failed: {e}")
PY

echo "[OK] datafactory_app.py vervangen."
echo
echo "Herstart nu de datafactory met:"
echo "  cd ~/Projects/RAG-ai3-chunk-embed"
echo "  source .venv/bin/activate"
echo "  uvicorn datafactory_app:app --host 0.0.0.0 --port 9000"
