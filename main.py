from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from embedding_service import embed_texts


app = FastAPI(
    title="AI-3 DataFactory",
    version="0.1.0",
)


# ---------- Pydantic modellen ----------

class IngestRequest(BaseModel):
    # minimale eis: text
    text: str

    # alles hieronder mag None zijn – zo voorkomen we 422
    tenant_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    document_type: str | None = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    analysis: Dict[str, Any] | None = None

    # onbekende velden gewoon negeren
    model_config = {"extra": "ignore"}


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


# simpele in-memory vectorstore
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
def ingest(req: IngestRequest) -> IngestResponse:
    """
    Ingest één documenttekst als één chunk.
    - Minimale vereiste: text
    - Alles rond tenant/project/user/metadata is optioneel.
    """
    try:
        text = (req.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="empty text")

        tenant_id = req.tenant_id or "default-tenant"
        project_id = req.project_id or "default-project"
        filename = req.filename or "unknown"

        doc_id = f"{tenant_id}:{project_id}:{filename}"

        # embedder – nu CPU of wat jij in embedding_service hebt
        vec = embed_texts([text])[0]

        meta: Dict[str, Any] = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "user_id": req.user_id or "",
            "filename": filename,
            "mime_type": req.mime_type,
        }

        if req.document_type:
            meta["document_type"] = req.document_type

        # extra metadata/analysis van buiten meekoppelen
        meta.update(req.metadata or {})
        if req.analysis is not None:
            meta["analysis"] = req.analysis

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
    Heel simpele cosine similarity search in de in-memory store.
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
