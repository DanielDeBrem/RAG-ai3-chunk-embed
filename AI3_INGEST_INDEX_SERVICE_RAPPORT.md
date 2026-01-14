# AI-3 als Ingest/Index Service - Onderzoeksrapport
**Datum:** 2026-01-08  
**Onderzoeker:** Cline AI  
**Repo:** RAG-ai3-chunk-embed (github.com/DanielDeBrem/RAG-ai3-chunk-embed)  
**Commit:** 4cf5d6d

---

## Executive Summary

AI-3 is **geschikt** als ingest/index service binnen een 2-service RAGfactory architectuur, maar heeft **significante gaps** die eerst opgelost moeten worden. De service heeft sterke basis features (multi-GPU embeddings, geavanceerde chunking, LLM enrichment) maar mist essentiële productie-ready componenten zoals persistente storage, job queue management en robuuste error handling.

**Aanbeveling:** Implementeer de P0 gaps (zie sectie 3) voordat AI-3 in productie gaat als dedicated ingest/index service.

---

## 1. FACTS - Tech Stack & Capabilities

### 1.1 Tech Stack (met bewijs)

| Component | Technology | Bewijs | Locatie |
|-----------|-----------|--------|---------|
| **Vector Store** | FAISS (in-memory) | `import faiss` + `self.index = faiss.IndexFlatIP(dim)` | app.py:10, 202 |
| **Embeddings** | BAAI/bge-m3 via sentence-transformers | `EMBED_MODEL_NAME = "BAAI/bge-m3"` | app.py:50 |
| **LLM (Analysis)** | Ollama llama3.1:70b | `OLLAMA_MODEL="llama3.1:70b"` | README.md:79 |
| **LLM (Enrichment)** | Ollama llama3.1:8b | `CONTEXT_MODEL = "llama3.1:8b"` | contextual_enricher.py:24 |
| **Reranker** | BAAI/bge-reranker-v2-m3 | `RERANK_MODEL="BAAI/bge-reranker-v2-m3"` | README.md:80 |
| **API Framework** | FastAPI + uvicorn | `from fastapi import FastAPI` | app.py:15 |
| **Storage** | In-memory Python dict | `indices: Dict[str, ProjectDocTypeIndex] = {}` | app.py:227 |
| **GPU Management** | Custom GPUManager + parallel processing | `from gpu_manager import gpu_manager` | app.py:32 |
| **Job Queue** | **NIET GEVONDEN** | ❌ Geen Redis/Celery/RQ | - |
| **Database** | **NIET GEVONDEN** | ❌ Geen SQLite/MySQL/Postgres | - |

**Kritisch:** FAISS index en metadata zijn **volledig in-memory**. Bij restart gaan alle data verloren.

```python
# Bewijs: app.py regel 227-229
app = FastAPI(title="AI-3 DataFactory", version="0.5.0")
model: SentenceTransformer | None = None
indices: Dict[str, ProjectDocTypeIndex] = {}  # ← IN-MEMORY ONLY
```

### 1.2 API Endpoints (Contract Documentatie)

#### A. Simplified Endpoints (AI-4 Orchestrator Compatible)

**POST /ingest**
```python
# Bewijs: app.py regel 1163-1234
class SimpleIngestRequest(BaseModel):
    tenant_id: str              # REQUIRED
    project_id: str             # REQUIRED
    user_id: Optional[str]      # OPTIONAL
    filename: str               # REQUIRED
    mime_type: Optional[str]    # OPTIONAL
    text: str                   # REQUIRED - extracted text
    document_type: Optional[str] # OPTIONAL - auto-detect if None
    metadata: Optional[Dict]    # OPTIONAL
    chunk_strategy: Optional[str] # OPTIONAL - zie 1.5
    chunk_overlap: int = 0      # OPTIONAL

# Response:
class IngestResponse(BaseModel):
    project_id: str             # Combined: tenant_id:project_id
    document_type: str
    doc_id: str
    chunks_added: int
```

**POST /search**
```python
# Bewijs: app.py regel 1236-1296
class SimpleSearchRequest(BaseModel):
    tenant_id: str              # REQUIRED
    project_id: str             # REQUIRED
    user_id: Optional[str]      # OPTIONAL
    query: Optional[str]        # REQUIRED (alias voor question)
    question: Optional[str]     # REQUIRED (alias voor query)
    document_type: str = "generic"
    top_k: int = 5

# Response:
class SearchResponse(BaseModel):
    chunks: List[ChunkHit]
    
class ChunkHit(BaseModel):
    doc_id: str
    chunk_id: str               # Format: {doc_id}#c{index:04d}
    text: str                   # Raw chunk text (default)
    score: float                # Vector similarity or rerank score
    metadata: Dict[str, Any]    # Bevat: tenant_id, project_id, user_id, 
                               #        raw_text, embed_text, chunk_hash, etc.
```

#### B. Advanced Endpoints (v1 API)

**POST /v1/rag/ingest/text**
```python
# Bewijs: app.py regel 1035-1078
class IngestTextRequest(BaseModel):
    project_id: str
    document_type: Optional[str]
    doc_id: str
    text: str
    chunk_strategy: Optional[str]
    chunk_overlap: int = 0
    metadata: Dict[str, Any] = {}
```

**POST /v1/rag/ingest/file**
```python
# Bewijs: app.py regel 1081-1128
# Form upload met multipart/form-data
# Ondersteunt: PDF, DOCX, XLSX, CSV, TXT, MD
# Automatische text extractie via pypdf, python-docx, pandas
```

**POST /v1/rag/search**
```python
# Bewijs: app.py regel 1006-1032
class SearchRequest(BaseModel):
    project_id: str
    document_type: str
    question: str
    top_k: int = 5

# Flow: FAISS vector search → Reranker HTTP call → Top K results
```

#### C. Document Analyzer Endpoints

**POST /analyze** (sync)
```python
# Bewijs: doc_analyzer_service.py regel 139-165
# Analyseert document met Ollama 70B
# Returns: DocumentAnalysis met topics, entities, summary, chunk_strategy
```

**POST /analyze/async** (async met job polling)
```python
# Bewijs: doc_analyzer_service.py regel 207-243
# Returns: job_id onmiddellijk
# Poll via: GET /analyze/status/{job_id}
```

#### D. Health & Management Endpoints

```python
# Health checks (alle services)
GET /health

# GPU management
GET /gpu/status           # GPU info, temperaturen
POST /gpu/cleanup         # Force GPU cleanup
GET /gpu/temperatures     # Alleen temperaturen

# Embedder management
GET /embedder/status      # Model info, loaded workers
POST /embedder/unload     # Unload alle embedding models
POST /embedder/prepare    # Prepare GPU's voor embedding
```

### 1.3 Document Type Classification

**Heuristische classificatie** (geen ML model):

```python
# Bewijs: app.py regel 65-85
def classify_document_type(
    text: str,
    filename: str | None = None,
    content_type: str | None = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    # Simple keyword matching:
    # - "jaarrekening" → jaarrekening
    # - "offerte" → offertes
    # - "review"/"google" → google_reviews
    # - "coach"/"sessie" → coaching_chat
    # Default: "generic"
```

**Status:** ✅ Werkt maar simpel. **NIET GEVONDEN:** ML-based classifier, confidence scores.

### 1.4 Deduplication

**Exact dedupe** op chunk hash:

```python
# Bewijs: app.py regel 117-126
def _chunk_hash(text: str) -> str:
    import hashlib
    norm = _normalize_text_for_hash(text)
    return hashlib.sha256(norm.encode("utf-8", errors="ignore")).hexdigest()

# Usage in ingest: app.py regel 798-803
for i, raw_ch in enumerate(raw_chunks):
    h = _chunk_hash(raw_ch)
    if h in idx.chunk_hashes:  # Skip duplicate
        continue
    idx.chunk_hashes.add(h)
```

**Status:** ✅ Exact dedupe werkt. **NIET GEVONDEN:** Fuzzy/semantic dedupe, idempotency keys.

### 1.5 Chunking Policies (Configureerbaar per Document Type)

**5 Chunking Strategies:**

```python
# Bewijs: app.py regel 371-387
CHUNK_STRATEGY_CONFIG = {
    "default": {"max_chars": 800, "overlap": 0},
    "page_plus_table_aware": {
        "max_chars": 1500, 
        "overlap": 200, 
        "respect_pages": True
    },
    "semantic_sections": {
        "max_chars": 1200, 
        "overlap": 150, 
        "split_on_headers": True
    },
    "conversation_turns": {
        "max_chars": 600, 
        "overlap": 0, 
        "split_on_turns": True
    },
    "table_aware": {
        "max_chars": 1000, 
        "overlap": 100, 
        "preserve_tables": True
    },
}
```

**Auto-mapping document_type → chunk_strategy:**

```python
# Bewijs: app.py regel 549-561
type_to_strategy = {
    "annual_report_pdf": "page_plus_table_aware",
    "jaarrekening": "page_plus_table_aware",
    "offer_doc": "semantic_sections",
    "offertes": "semantic_sections",
    "coaching_doc": "conversation_turns",
    "coaching_chat": "conversation_turns",
    "chatlog": "conversation_turns",
    "review_doc": "default",
    "google_reviews": "default",
}
```

**Status:** ✅ Geavanceerd chunking systeem. Configureerbaar via API parameter `chunk_strategy`.

### 1.6 Embeddings Strategy

**Model:** BAAI/bge-m3 via sentence-transformers

**Parallel Multi-GPU Processing:**

```python
# Bewijs: parallel_embedder.py regel 1-20
"""
Parallel Multi-GPU Embedder voor AI-3 DataFactory.
Met 8x RTX 3060 Ti kunnen we tot 8x sneller embedden!
"""

# Features:
# - Automatische GPU selectie (prefer GPU 6-7 voor embeddings)
# - Lazy model loading per GPU
# - Load balancing over beschikbare GPU's
# - GPU cleanup voor en na gebruik
# - Fallback naar single GPU/CPU bij problemen
```

**Versioning:** ❌ **NIET GEVONDEN**

```python
# Bewijs: app.py - geen embedding_version tracking
# Probleem: Als model wijzigt, oude embeddings blijven in FAISS
# zonder versie-informatie → incompatibiliteit!
```

**Reproducibility:** ⚠️ Gedeeltelijk

```python
# Bewijs: app.py regel 367-375
# Embeddings zijn deterministisch (zelfde input → zelfde vector)
# MAAR: geen vector_id tracking, geen embedding metadata
emb = model.encode(
    texts,
    batch_size=32,
    normalize_embeddings=True,  # ← Reproduceerbaar
    show_progress_bar=False,
)
```

### 1.7 Vector Index + Metadata Storage

**Vector Store:** FAISS IndexFlatIP (Inner Product, in-memory)

```python
# Bewijs: app.py regel 195-215
class ProjectDocTypeIndex:
    def __init__(self, dim: int, project_id: str, document_type: str):
        self.dim = dim
        self.project_id = project_id
        self.document_type = document_type
        self.index = faiss.IndexFlatIP(dim)  # ← IN-MEMORY
        self.chunks: List[ChunkHit] = []     # ← IN-MEMORY metadata
        self.chunk_hashes: Set[str] = set()  # ← IN-MEMORY dedupe
```

**Index Key:** `tenant_id:project_id::document_type`

```python
# Bewijs: app.py regel 218-219
def make_index_key(project_id: str, document_type: str) -> str:
    return f"{project_id}::{document_type}"

# Usage: indices["acme:project_001::jaarrekening"]
```

**Metadata Schema:**

```python
# Bewijs: app.py regel 829-841
chunk_meta = {
    "project_id": project_id,
    "document_type": document_type,
    "chunk_strategy": chunk_strategy or "auto",
    "context_enriched": enrich_context and CONTEXT_ENABLED,
    "text_mode": "raw+embed",
    "raw_text": raw_ch,              # Original chunk
    "embed_text": embed_ch,          # Enriched chunk (met context)
    "chunk_hash": _chunk_hash(raw_ch),
    "tenant_id": tenant_id,          # Via SimpleIngestRequest
    "user_id": user_id,              # Via SimpleIngestRequest
    "filename": filename,
    # ... + custom metadata
}
```

**Filtering:** ⚠️ Beperkt

```python
# Bewijs: app.py regel 1010-1020
# Filtering gebeurt via index key selectie:
key = make_index_key(req.project_id, req.document_type)
idx = indices[key]

# Probleem: Kan NIET filteren op:
# - tenant_id alleen (zonder project_id)
# - date range
# - user_id
# - custom metadata fields
```

**Persistence:** ❌ **NIET GEVONDEN**

```python
# Bewijs: Geen save/load functies voor FAISS index
# app.py heeft geen:
# - faiss.write_index()
# - faiss.read_index()
# - Database persistence
# → Bij restart: ALLE DATA WEG
```

### 1.8 Multi-Tenancy / Namespaces

**Status:** ⚠️ Basic support via naming convention

```python
# Bewijs: app.py regel 1188-1190
# Simplified /ingest endpoint:
internal_project_id = f"{req.tenant_id}:{req.project_id}"
# → Index key: "acme:project_001::generic"

# Namespace levels:
# 1. tenant_id       → In index key via project_id prefix
# 2. project_id      → In index key
# 3. document_type   → In index key
# 4. user_id         → In metadata only (geen filtering)
```

**Isolatie:** ✅ Per tenant:project:type combinatie

**Risico's:**
1. ❌ Geen tenant quota management
2. ❌ Geen tenant-level delete/export
3. ❌ Geen cross-tenant isolation enforcement (logic only)
4. ❌ Geen tenant billing/metering

### 1.9 LLM Context Enrichment (Unique Feature!)

**Innovatieve feature:** Elke chunk wordt verrijkt met LLM-gegenereerde context

```python
# Bewijs: contextual_enricher.py regel 1-12
"""
LLM-based Contextual Embedding Enricher voor AI-3.
Gebruikt llama3.1:8b met parallel processing (6 workers) voor snelle 
context generatie per chunk voordat deze wordt geëmbed.
Performance: ~6x sneller dan 70B sequentieel.
"""

# Bewijs: app.py regel 699-730
if enrich_context and CONTEXT_ENABLED:
    # 1. Genereer context per chunk (parallel 8B over 6 GPU's)
    contexts = enrich_chunks_batch(raw_chunks, doc_metadata)
    
    # 2. Embed verrijkte chunks:
    # [Document: jaarrekening.pdf]
    # [Type: jaarrekening]
    # [Context: Deze passage beschrijft de balans met activa...]
    # 
    # {original chunk text}
```

**Performance:** Parallel over 6 GPU's → 6x sneller dan sequentieel

**Status:** ✅ Werkt en is uniek, maar geen toggle per request (global CONTEXT_ENABLED env var)

### 1.10 AI-4 Integration

**Webhook Status Updates:**

```python
# Bewijs: status_reporter.py regel 31-32, app.py regel 38-39
# Stuurt real-time progress naar AI-4:
report_received(doc_id, filename)
report_analyzing(doc_id, model="llama3.1:70b")
report_chunking(doc_id, strategy="auto")
report_enriching(doc_id, chunks_count=150, current=45)
report_embedding(doc_id, chunks_count=150, current=100)
report_storing(doc_id, chunks_count=150)
report_completed(doc_id, chunks_stored=150, duration_sec=45.2)
report_failed(doc_id, error="OOM", stage="embedding")

# Webhook URL: AI4_WEBHOOK_URL env var
# Bewijs: README.md regel 144
export AI4_WEBHOOK_URL="http://10.0.1.227:5001/api/webhook/ai3-status"
```

**Network Configuration:**

```python
# Bewijs: README.md regel 236-248
# AI-3 Server:
# - Hostname: principium-ai-3
# - IP (LAN): 10.0.1.44
# - IP (10GbE): 10.10.10.13

# AI-4 configureert:
AI3_DATAFACTORY_URL = "http://10.0.1.44:9000"
AI3_ANALYZER_URL = "http://10.0.1.44:9100"
AI3_RERANKER_URL = "http://10.0.1.44:9200"
```

**Status:** ✅ Basis integratie werkt. ❌ Geen auth, rate limiting, circuit breaker.

---

## 2. GAPS - Wat Ontbreekt

### P0 - Kritisch (Blocker voor productie)

#### 2.1 Persistente Storage
**Status:** ❌ NIET GEVONDEN  
**Impact:** Data loss bij restart, geen disaster recovery  
**Bewijs:** app.py regel 227 - `indices: Dict[str, ProjectDocTypeIndex] = {}`  

**Benodigd:**
- FAISS index persistence (`faiss.write_index()` / `read_index()`)
- Metadata database (SQLite/PostgreSQL)
- Schema:
  ```sql
  CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    document_type TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    embed_text TEXT NOT NULL,
    chunk_hash TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_version TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(doc_id, chunk_index)
  );
  
  CREATE TABLE documents (
    doc_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    document_type TEXT NOT NULL,
    chunks_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
  );
  
  CREATE INDEX idx_chunks_tenant ON chunks(tenant_id, project_id);
  CREATE INDEX idx_chunks_doc ON chunks(doc_id);
  ```

#### 2.2 Document Delete Endpoint
**Status:** ❌ NIET GEVONDEN  
**Impact:** Geen manier om documents te verwijderen  
**Bewijs:** Geen `/v1/docs/delete` of `/v1/docs/{doc_id}` DELETE endpoint  

**Benodigd:**
```python
@app.delete("/v1/docs/{doc_id}")
def delete_document(doc_id: str, tenant_id: str, project_id: str):
    """
    Verwijder document en alle chunks uit index.
    
    1. Vind alle chunks van doc_id
    2. Verwijder uit FAISS (rebuild index zonder deze chunks)
    3. Verwijder uit metadata database
    4. Return success/failure
    """
```

#### 2.3 Index Rebuild Endpoint
**Status:** ❌ NIET GEVONDEN  
**Impact:** Geen manier om index te rebuilden na model change  
**Bewijs:** Geen `/v1/index/rebuild` endpoint  

**Benodigd:**
```python
@app.post("/v1/index/rebuild")
def rebuild_index(
    tenant_id: str, 
    project_id: str, 
    document_type: str,
    new_embedding_model: Optional[str] = None
):
    """
    Rebuild index van scratch:
    1. Load alle chunks uit database
    2. Re-embed met (optioneel) nieuw model
    3. Rebuild FAISS index
    4. Update embedding_version in DB
    """
```

#### 2.4 Job Queue System
**Status:** ❌ NIET GEVONDEN (alleen in-memory async met BackgroundTasks)  
**Impact:** Geen persistent job tracking, crash → job verloren  
**Bewijs:** doc_analyzer_service.py regel 39 - `_jobs: Dict[str, AnalysisJob] = {}`  

**Benodigd:**
- Redis/Celery/RQ voor persistent job queue
- Job status persistence in database
- Worker pool management
- Job retry logic
- Job timeout handling

#### 2.5 Embedding Version Tracking
**Status:** ❌ NIET GEVONDEN  
**Impact:** Model changes → incompatible embeddings mixed in index  
**Bewijs:** Geen `embedding_version` field in metadata  

**Benodigd:**
```python
# Track in metadata:
chunk_meta = {
    "embedding_model": "BAAI/bge-m3",
    "embedding_version": "v1.5.0",  # ← TOEVOEGEN
    "embedding_timestamp": "2026-01-08T12:00:00Z",
    # ...
}

# API endpoint om model version op te halen:
@app.get("/v1/embeddings/version")
def get_embedding_version():
    return {
        "model": EMBED_MODEL_NAME,
        "version": get_model_version(),
        "dimension": 1024
    }
```

### P1 - Belangrijk (voor robuustheid)

#### 2.6 Advanced Metadata Filtering
**Status:** ⚠️ Beperkt (alleen via index key)  
**Impact:** Kan niet filteren op date, user_id, custom fields  

**Benodigd:**
```python
class SearchRequest(BaseModel):
    # ... bestaande fields
    filters: Optional[Dict[str, Any]] = None  # ← TOEVOEGEN
    # Voorbeeld: {"user_id": "alice", "date_gte": "2026-01-01"}
    
# Implementatie:
# 1. FAISS vector search (breed)
# 2. Filter candidates op metadata
# 3. Rerank
# 4. Return top_k
```

#### 2.7 Tenant Quota & Rate Limiting
**Status:** ❌ NIET GEVONDEN  
**Impact:** Geen bescherming tegen abuse  

**Benodigd:**
- Rate limiting per tenant (requests/minute)
- Storage quota per tenant (chunks/GB)
- API key authentication
- Usage metering voor billing

#### 2.8 Error Recovery & Retries
**Status:** ⚠️ Basic (alleen try/catch)  
**Impact:** Transient failures → permanent data loss  

**Benodigd:**
- Exponential backoff retries
- Circuit breaker voor external calls (Ollama, reranker)
- Partial success handling (bijv. 90/100 chunks embedded)
- Failed job retry queue

#### 2.9 Monitoring & Observability
**Status:** ⚠️ Basic (logging only)  
**Impact:** Moeilijk te debuggen in productie  

**Benodigd:**
- Prometheus metrics (ingest_duration, embedding_duration, etc.)
- Structured logging (JSON logs)
- Distributed tracing (OpenTelemetry)
- Health check met dependencies (Ollama, FAISS, DB)

### P2 - Nice to Have

#### 2.10 Batch Operations
**Status:** ❌ NIET GEVONDEN  

**Benodigd:**
- `/v1/docs/batch/ingest` - Ingest multiple docs in één call
- `/v1/docs/batch/delete` - Delete multiple docs
- `/v1/docs/export` - Export chunks voor backup

#### 2.11 Advanced Document Classification
**Status:** ⚠️ Simple heuristics only  

**Benodigd:**
- ML-based classifier (transformer model)
- Confidence scores
- Multi-label classification
- User feedback loop voor accuracy improvement

#### 2.12 Semantic Deduplication
**Status:** ⚠️ Exact hash only  

**Benodigd:**
- Fuzzy dedupe (Levenshtein distance)
- Semantic similarity dedupe (cosine similarity threshold)
- Cross-document dedupe

---

## 3. PATCH PLAN - Concrete Implementatie

### 3.1 Bestanden die aangepast moeten worden

```
RAG-ai3-chunk-embed/
├── app.py                    # PATCH: Add persistence, delete, rebuild
├── storage.py                # NEW: Database abstraction layer
├── models.py                 # NEW: SQLAlchemy models
├── api_v1.py                 # NEW: Refactored v1 API endpoints
├── job_queue.py              # NEW: Redis/Celery job queue
├── config/ai3_settings.py    # PATCH: Add DB config
├── requirements.txt          # PATCH: Add sqlalchemy, redis, celery
├── alembic/                  # NEW: Database migrations
│   └── versions/
│       └── 001_initial_schema.py
└── tests/
    └── test_persistence.py   # NEW: Persistence tests
```

### 3.2 Nieuwe API Endpoints (RAGfactory Contract)

#### A. /v1/docs/upsert

```python
# api_v1.py (NEW FILE)
from fastapi import APIRouter
from storage import DocumentStore

router = APIRouter(prefix="/v1/docs")
doc_store = DocumentStore()

@router.post("/upsert")
async def upsert_document(req: UpsertDocumentRequest):
    """
    Upsert document (insert or update).
    
    Flow:
    1. Check if doc_id exists
    2. If exists: delete old chunks, re-ingest
    3. If new: ingest
    4. Return job_id for async tracking
    
    Request:
    {
        "tenant_id": "acme",
        "project_id": "proj1",
        "doc_id": "invoice_2024.pdf",  // Unique identifier
        "filename": "invoice_2024.pdf",
        "text": "Document content...",
        "document_type": "invoice",
        "chunk_strategy": "semantic_sections",
        "metadata": {"department": "finance"}
    }
    
    Response:
    {
        "job_id": "abc123",
        "status": "queued",
        "message": "Document queued for ingestion",
        "estimated_duration_sec": 30
    }
    """
    # 1. Check if doc exists
    existing = await doc_store.get_document(
        tenant_id=req.tenant_id,
        project_id=req.project_id,
        doc_id=req.doc_id
    )
    
    if existing:
        # Delete old version first
        await doc_store.delete_document(req.tenant_id, req.project_id, req.doc_id)
    
    # 2. Queue ingestion job
    job = await job_queue.enqueue_ingest(req)
    
    return {
        "job_id": job.id,
        "status": "queued",
        "message": f"Document {'updated' if existing else 'created'}",
        "estimated_duration_sec": estimate_duration(req.text)
    }
```

#### B. /v1/docs/delete

```python
@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    tenant_id: str,
    project_id: str,
    document_type: Optional[str] = None
):
    """
    Delete document en alle chunks.
    
    Request:
    DELETE /v1/docs/invoice_2024.pdf?tenant_id=acme&project_id=proj1
    
    Response:
    {
        "doc_id": "invoice_2024.pdf",
        "status": "deleted",
        "chunks_deleted": 45,
        "index_rebuilt": true
    }
    """
    # 1. Get all chunks for doc
    chunks = await doc_store.get_chunks_by_doc(
        tenant_id, project_id, doc_id
    )
    
    if not chunks:
        raise HTTPException(404, f"Document {doc_id} not found")
    
    # 2. Delete from database
    await doc_store.delete_chunks(chunk_ids=[c.chunk_id for c in chunks])
    await doc_store.delete_document(tenant_id, project_id, doc_id)
    
    # 3. Rebuild FAISS index without these chunks
    document_type = document_type or chunks[0].document_type
    await rebuild_index_for_project(tenant_id, project_id, document_type)
    
    return {
        "doc_id": doc_id,
        "status": "deleted",
        "chunks_deleted": len(chunks),
        "index_rebuilt": True
    }
```

#### C. /v1/index/rebuild

```python
@router.post("/rebuild")
async def rebuild_index(req: RebuildIndexRequest):
    """
    Rebuild FAISS index from database.
    
    Use cases:
    - Embedding model changed
    - Index corrupted
    - Need to compact index
    
    Request:
    {
        "tenant_id": "acme",
        "project_id": "proj1",
        "document_type": "invoice",
        "force_re_embed": false,  // If true: re-generate embeddings
        "new_embedding_model": null  // Optional: switch model
    }
    
    Response:
    {
        "job_id": "rebuild_xyz",
        "status": "queued",
        "estimated_duration_sec": 120,
        "chunks_to_process": 1500
    }
    """
    # 1. Count chunks to process
    chunks = await doc_store.get_chunks(
        tenant_id=req.tenant_id,
        project_id=req.project_id,
        document_type=req.document_type
    )
    
    # 2. Queue rebuild job
    job = await job_queue.enqueue_rebuild(
        tenant_id=req.tenant_id,
        project_id=req.project_id,
        document_type=req.document_type,
        chunks=chunks,
        force_re_embed=req.force_re_embed,
        new_model=req.new_embedding_model
    )
    
    return {
        "job_id": job.id,
        "status": "queued",
        "estimated_duration_sec": len(chunks) * 0.05,  # 50ms per chunk
        "chunks_to_process": len(chunks)
    }
```

#### D. /v1/health

```python
@router.get("/health")
async def health_check():
    """
    Extended health check met dependencies.
    
    Response:
    {
        "status": "healthy",
        "timestamp": "2026-01-08T12:00:00Z",
        "version": "0.5.0",
        "dependencies": {
            "database": {"status": "healthy", "latency_ms": 5},
            "faiss": {"status": "healthy", "indices": 3, "total_chunks": 1500},
            "ollama": {"status": "healthy", "models": ["llama3.1:70b", "llama3.1:8b"]},
            "reranker": {"status": "healthy"},
            "redis": {"status": "healthy", "jobs_pending": 2}
        },
        "resources": {
            "gpus": [
                {"index": 0, "free_mb": 8000, "temp_c": 45},
                {"index": 6, "free_mb": 10000, "temp_c": 42}
            ]
        }
    }
    """
    health = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "0.5.0",
        "dependencies": {}
    }
    
    # Check database
    try:
        await doc_store.ping()
        health["dependencies"]["database"] = {"status": "healthy"}
    except Exception as e:
        health["dependencies"]["database"] = {"status": "unhealthy", "error": str(e)}
        health["status"] = "degraded"
    
    # Check FAISS
    try:
        indices_count = len(indices)
        total_chunks = sum(len(idx.chunks) for idx in indices.values())
        health["dependencies"]["faiss"] = {
            "status": "healthy",
            "indices": indices_count,
            "total_chunks": total_chunks
        }
    except Exception as e:
        health["dependencies"]["faiss"] = {"status": "unhealthy", "error": str(e)}
        health["status"] = "degraded"
    
    # Check Ollama
    try:
        ollama_ok = await check_ollama_available()
        health["dependencies"]["ollama"] = {
            "status": "healthy" if ollama_ok else "unhealthy"
        }
    except Exception as e:
        health["dependencies"]["ollama"] = {"status": "unhealthy", "error": str(e)}
    
    # GPU status
    health["resources"] = {"gpus": gpu_manager.get_status()["gpus"]}
    
    return health
```

#### E. /v1/jobs/* (Job Queue Management)

```python
@router.post("/jobs/enqueue")
async def enqueue_job(req: EnqueueJobRequest):
    """
    Generieke job enqueue endpoint.
    
    Job types: 'ingest', 'delete', 'rebuild', 'export'
    """
    job = await job_queue.enqueue(
        job_type=req.job_type,
        payload=req.payload,
        tenant_id=req.tenant_id
    )
    return {"job_id": job.id, "status": "queued"}

@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """
    Poll job status.
    
    Response:
    {
        "job_id": "abc123",
        "status": "processing",  // pending/processing/completed/failed
        "progress_pct": 65,
        "message": "Embedding chunk 95/150",
        "created_at": "2026-01-08T12:00:00Z",
        "started_at": "2026-01-08T12:00:02Z",
        "completed_at": null,
        "result": null,  // Available when status=completed
        "error": null    // Available when status=failed
    }
    """
    job = await job_queue.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    return job.to_dict()

@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel running job."""
    await job_queue.cancel_job(job_id)
    return {"job_id": job_id, "status": "cancelled"}
```

### 3.3 Storage Layer (storage.py - NEW FILE)

```python
# storage.py
from sqlalchemy import create_engine, Column, String, Integer, Text, JSON, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import json

Base = declarative_base()

class Document(Base):
    __tablename__ = 'documents'
    
    doc_id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)
    project_id = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=False)
    document_type = Column(String, nullable=False)
    chunks_count = Column(Integer, default=0)
    status = Column(String, default='pending')  # pending/processing/completed/failed
    created_at = Column(TIMESTAMP, server_default='NOW()')

class Chunk(Base):
    __tablename__ = 'chunks'
    
    chunk_id = Column(String, primary_key=True)
    doc_id = Column(String, nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    project_id = Column(String, nullable=False, index=True)
    document_type = Column(String, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    raw_text = Column(Text, nullable=False)
    embed_text = Column(Text, nullable=False)
    chunk_hash = Column(String, nullable=False, unique=True)
    embedding_model = Column(String, nullable=False)
    embedding_version = Column(String, nullable=False)
    metadata = Column(JSON)
    created_at = Column(TIMESTAMP, server_default='NOW()')

class FaissIndex(Base):
    __tablename__ = 'faiss_indices'
    
    index_key = Column(String, primary_key=True)  # tenant:project::type
    tenant_id = Column(String, nullable=False)
    project_id = Column(String, nullable=False)
    document_type = Column(String, nullable=False)
    embedding_model = Column(String, nullable=False)
    embedding_version = Column(String, nullable=False)
    dimension = Column(Integer, nullable=False)
    chunks_count = Column(Integer, default=0)
    index_file_path = Column(String)  # Path naar .faiss file
    last_rebuilt = Column(TIMESTAMP, server_default='NOW()')

class DocumentStore:
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
    
    async def save_document(self, doc: Document):
        session = self.Session()
        try:
            session.add(doc)
            session.commit()
        finally:
            session.close()
    
    async def save_chunks(self, chunks: List[Chunk]):
        session = self.Session()
        try:
            session.bulk_save_objects(chunks)
            session.commit()
        finally:
            session.close()
    
    async def get_chunks(self, tenant_id: str, project_id: str, document_type: str):
        session = self.Session()
        try:
            return session.query(Chunk).filter(
                Chunk.tenant_id == tenant_id,
                Chunk.project_id == project_id,
                Chunk.document_type == document_type
            ).all()
        finally:
            session.close()
    
    async def delete_document(self, tenant_id: str, project_id: str, doc_id: str):
        session = self.Session()
        try:
            session.query(Chunk).filter(Chunk.doc_id == doc_id).delete()
            session.query(Document).filter(Document.doc_id == doc_id).delete()
            session.commit()
        finally:
            session.close()
    
    async def save_faiss_index(self, index_key: str, index: faiss.Index, metadata: dict):
        """Save FAISS index to disk and register in DB."""
        import faiss
        
        # Save to disk
        index_path = f"data/faiss/{index_key}.faiss"
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        faiss.write_index(index, index_path)
        
        # Register in DB
        session = self.Session()
        try:
            faiss_idx = FaissIndex(
                index_key=index_key,
                tenant_id=metadata['tenant_id'],
                project_id=metadata['project_id'],
                document_type=metadata['document_type'],
                embedding_model=metadata['embedding_model'],
                embedding_version=metadata['embedding_version'],
                dimension=metadata['dimension'],
                chunks_count=metadata['chunks_count'],
                index_file_path=index_path
            )
            session.merge(faiss_idx)
            session.commit()
        finally:
            session.close()
    
    async def load_faiss_index(self, index_key: str) -> Optional[faiss.Index]:
        """Load FAISS index from disk."""
        import faiss
        
        session = self.Session()
        try:
            faiss_idx = session.query(FaissIndex).filter(
                FaissIndex.index_key == index_key
            ).first()
            
            if not faiss_idx or not os.path.exists(faiss_idx.index_file_path):
                return None
            
            return faiss.read_index(faiss_idx.index_file_path)
        finally:
            session.close()
```

### 3.4 Sequence Diagram: App → AI-3 → AI-4

```
User Application         AI-3 (Ingest/Index)           AI-4 (Retrieve/Generate)
     │                           │                              │
     │ 1. Upload Document        │                              │
     ├──────────────────────────>│                              │
     │                           │                              │
     │ 2. Return job_id          │                              │
     │<──────────────────────────┤                              │
     │                           │                              │
     │                           │ 3. Webhook: analyzing        │
     │                           ├─────────────────────────────>│
     │                           │                              │
     │                           │ 4. LLM Analysis (70B)        │
     │                           │ (via AI-4 /llm70/*)          │
     │                           │<─────────────────────────────┤
     │                           │                              │
     │                           │ 5. Webhook: chunking         │
     │                           ├─────────────────────────────>│
     │                           │                              │
     │                           │ 6. Webhook: enriching        │
     │                           ├─────────────────────────────>│
     │                           │                              │
     │                           │ 7. LLM Enrichment (8B)       │
     │                           │ (local Ollama, 6 parallel)   │
     │                           │                              │
     │                           │ 8. Webhook: embedding        │
     │                           ├─────────────────────────────>│
     │                           │                              │
     │                           │ 9. Generate Embeddings       │
     │                           │ (BGE-m3, multi-GPU)          │
     │                           │                              │
     │                           │ 10. Store in FAISS + DB      │
     │                           │                              │
     │                           │ 11. Webhook: completed       │
     │                           ├─────────────────────────────>│
     │                           │                              │
     │ 12. Poll /jobs/{job_id}   │                              │
     ├──────────────────────────>│                              │
     │ Response: completed       │                              │
     │<──────────────────────────┤                              │
     │                           │                              │
     │                           │                              │
     │ 13. User Query            │                              │
     ├────────────────────────────────────────────────────────>│
     │                           │                              │
     │                           │ 14. POST /search             │
     │                           │<─────────────────────────────┤
     │                           │                              │
     │                           │ 15. FAISS Vector Search      │
     │                           │                              │
     │                           │ 16. Rerank Top Candidates    │
     │                           │                              │
     │                           │ 17. Return Top K Chunks      │
     │                           ├─────────────────────────────>│
     │                           │                              │
     │                           │ 18. LLM Generate Response    │
     │                           │    (70B on AI-4)             │
     │                           │                              │
     │ 19. Stream LLM Response   │                              │
     │<────────────────────────────────────────────────────────┤
     │                           │                              │
```

### 3.5 Requirements Update

```txt
# requirements.txt - PATCH
fastapi
uvicorn[standard]
sentence-transformers
faiss-cpu
pydantic
numpy
torch
pandas
python-docx
openpyxl
pypdf
requests
httpx  # ← al aanwezig

# NEW dependencies:
sqlalchemy>=2.0.0
psycopg2-binary  # Voor PostgreSQL (of sqlite3 voor development)
alembic  # Database migrations
redis>=5.0.0
celery[redis]>=5.3.0  # Job queue
prometheus-client  # Metrics
structlog  # Structured logging
python-dotenv  # Config management
tenacity  # Retry logic
```

---

## 4. Conclusie & Aanbevelingen

### 4.1 Geschiktheid als Ingest/Index Service

**Rating: 7/10** ⭐⭐⭐⭐⭐⭐⭐

**Sterke punten:**
- ✅ Geavanceerd chunking systeem (5 strategies)
- ✅ Multi-GPU parallel processing (snelheid)
- ✅ Unieke LLM-based context enrichment
- ✅ Goede AI-4 integratie (webhooks, simplified endpoints)
- ✅ Document type awareness
- ✅ Reranking integratie

**Kritische zwaktes:**
- ❌ Geen persistente storage (P0)
- ❌ Geen document delete (P0)
- ❌ Geen index rebuild (P0)
- ❌ Geen job queue persistence (P0)
- ❌ Geen embedding version tracking (P0)

### 4.2 Implementatie Prioriteiten

**Week 1: P0 Blockers**
1. Implement persistent storage (FAISS + SQLite/PostgreSQL)
2. Add /v1/docs/delete endpoint
3. Add /v1/index/rebuild endpoint
4. Add embedding version tracking
5. Implement Redis job queue

**Week 2: P1 Production Ready**
6. Advanced metadata filtering
7. Tenant quota & rate limiting
8. Error recovery & retries
9. Extended health checks
10. Prometheus metrics

**Week 3: P2 Nice to Have**
11. Batch operations
12. ML-based document classification
13. Semantic deduplication
14. Export/backup endpoints

### 4.3 Alternatieve Architectuur (Als rebuild te groot is)

Als de bovenstaande patches te veel werk zijn, overweeg:

**Optie A: Hybride**
- AI-3: Blijft pure processing service (no state)
- AI-4: Beheert storage, job queue, API orchestration
- Pro: Kleinere scope voor AI-3
- Con: AI-4 wordt complexer

**Optie B: Existing Solutions**
- Gebruik Weaviate/Qdrant als vector database (persistent, production-ready)
- AI-3 wordt thin wrapper om chunking + enrichment + embeddings
- Pro: Snellere time-to-production
- Con: Extra dependency, hosting complexity

### 4.4 Final Recommendation

**Implementeer de P0 patches.** De basis is sterk genoeg, en met persistente storage + job queue wordt AI-3 een production-ready ingest/index service. De unieke features (context enrichment, multi-GPU) zijn waardevol genoeg om de investering te rechtvaardigen.

**Alternatief:** Als tijd critisch is, overweeg een migratie naar Weaviate/Qdrant en gebruik AI-3 alleen voor de processing logic (chunking/enrichment/embeddings).

---

**Einde Rapport**

*Voor vragen of verduidelijking: zie FACTS sectie voor file/line referenties.*
