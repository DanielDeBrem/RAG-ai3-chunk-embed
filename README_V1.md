# AI-3 DataFactory v1 - Persistent RAG Service

**Production-ready ingest/index service with persistence, crash-safety, and idempotent operations.**

## 🎯 P0 Features (Implemented)

✅ **Persistent Storage**: SQLite database + FAISS indices on disk  
✅ **Idempotent Upserts**: Same doc_id with same content = skip, different = update  
✅ **Document Deletion**: Soft delete with async rebuild  
✅ **Atomic Operations**: FAISS index swapping (temp → fsync → rename)  
✅ **Persistent Job Queue**: SQLite-backed, survives crashes  
✅ **Crash-Safe**: Restart-safe, no data loss  
✅ **Deleted Chunk Filtering**: Retrieval never returns deleted chunks  

---

## 📦 Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database (auto-created on first run)
# Default: sqlite:///./ai3_rag.db
```

---

## 🚀 Quick Start

### 1. Start API Server

```bash
# Default: http://0.0.0.0:8000
python -m uvicorn app_v1:app --host 0.0.0.0 --port 8000

# With custom database
DATABASE_URL=sqlite:///./my_rag.db uvicorn app_v1:app --port 8000
```

### 2. Start Worker (Required for async jobs)

```bash
# In separate terminal
python worker.py

# With custom settings
python worker.py --poll-interval 2.0 --database-url sqlite:///./my_rag.db
```

### 3. Health Check

```bash
curl http://localhost:8000/v1/health
```

---

## 🔧 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./ai3_rag.db` | Database connection string |
| `INDEX_DIR` | `./faiss_indices` | Directory for FAISS index files |
| `EMBEDDING_VERSION` | `BAAI/bge-m3` | Embedding model version identifier |
| `EMBED_MODEL_NAME` | `BAAI/bge-m3` | SentenceTransformer model name |

**Example:**
```bash
export DATABASE_URL="sqlite:///./production.db"
export INDEX_DIR="/mnt/fast_ssd/faiss_indices"
export EMBEDDING_VERSION="bge-m3-v1"
```

---

## 📡 API Endpoints

All endpoints are versioned under `/v1/*`.

### Upsert Document (Sync)

```bash
curl -X POST http://localhost:8000/v1/docs/upsert \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "namespace": "project_001",
    "doc_id": "doc_123",
    "text": "Your document content here...",
    "metadata": {"filename": "doc.pdf"},
    "chunk_strategy": "default",
    "chunk_overlap": 0,
    "enrich_context": true
  }'
```

**Response:**
```json
{
  "accepted": 1,
  "upserted_docs": 1,
  "skipped_docs": 0,
  "chunks_created": 5,
  "job_id": null
}
```

**Idempotency:** Re-uploading same content → `skipped_docs: 1`, `chunks_created: 0`

---

### Upsert Multiple Documents (Async)

```bash
curl -X POST http://localhost:8000/v1/docs/upsert/batch \
  -H "Content-Type: application/json" \
  -d '{
    "async_mode": true,
    "docs": [
      {
        "tenant_id": "acme",
        "namespace": "project_001",
        "doc_id": "doc_001",
        "text": "First document..."
      },
      {
        "tenant_id": "acme",
        "namespace": "project_001",
        "doc_id": "doc_002",
        "text": "Second document..."
      }
    ]
  }'
```

**Response:**
```json
{
  "accepted": 2,
  "upserted_docs": 0,
  "skipped_docs": 0,
  "chunks_created": 0,
  "job_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### Delete Document

```bash
curl -X DELETE "http://localhost:8000/v1/docs/doc_123?tenant_id=acme&namespace=project_001"
```

**Response:**
```json
{
  "deleted": true,
  "doc_id": "doc_123",
  "chunks_deleted": 5,
  "job_id": "rebuild-job-uuid"
}
```

**Note:** 
- Soft delete (data preserved in DB)
- Triggers async rebuild job
- Deleted chunks filtered from search immediately

---

### Search (Retrieval)

```bash
curl -X POST http://localhost:8000/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "namespace": "project_001",
    "query": "What is the document about?",
    "top_k": 5
  }'
```

**Response:**
```json
{
  "chunks": [
    {
      "doc_id": "doc_123",
      "chunk_id": "doc_123#c0001",
      "text": "This document discusses...",
      "score": 0.92,
      "metadata": {"filename": "doc.pdf"}
    }
  ],
  "total_found": 3
}
```

**Guarantees:**
- ✅ Deleted chunks never returned
- ✅ Consistent with DB state
- ✅ Handles dirty indices gracefully

---

### Rebuild Index

```bash
curl -X POST http://localhost:8000/v1/index/rebuild \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "namespace": "project_001",
    "reembed": false
  }'
```

**Response:**
```json
{
  "job_id": "rebuild-uuid",
  "status": "pending"
}
```

**Options:**
- `reembed: false` → Use existing chunks, rebuild FAISS only
- `reembed: true` → Re-embed all chunks (model upgrade)
- `new_embedding_version` → Tag with new version

---

### Job Status

```bash
curl http://localhost:8000/v1/jobs/{job_id}
```

**Response:**
```json
{
  "job_id": "uuid",
  "type": "rebuild_index",
  "status": "completed",
  "progress": 100,
  "error": null,
  "created_at": "2026-01-08T13:00:00",
  "updated_at": "2026-01-08T13:01:30",
  "started_at": "2026-01-08T13:00:05",
  "completed_at": "2026-01-08T13:01:30"
}
```

**Statuses:** `pending`, `running`, `completed`, `failed`

---

### Health Check

```bash
curl http://localhost:8000/v1/health
```

**Response:**
```json
{
  "ok": true,
  "db_ok": true,
  "index_store_ok": true,
  "jobqueue_ok": true,
  "build_info": {
    "version": "1.0.0",
    "embedding_model": "BAAI/bge-m3",
    "embedding_version": "BAAI/bge-m3",
    "database_url": "sqlite:///./ai3_rag.db",
    "index_dir": "./faiss_indices"
  }
}
```

---

### Index Statistics

```bash
curl http://localhost:8000/v1/index/stats
```

**Response:**
```json
{
  "total_indices": 3,
  "total_vectors": 1523,
  "dirty_indices": 1,
  "indices": [
    {
      "tenant_id": "acme",
      "namespace": "project_001",
      "embedding_version": "BAAI/bge-m3",
      "ntotal": 842,
      "dimension": 1024,
      "dirty": false,
      "updated_at": "2026-01-08T12:30:00"
    }
  ]
}
```

---

### Queue Statistics

```bash
curl http://localhost:8000/v1/queue/stats
```

**Response:**
```json
{
  "total": 15,
  "pending": 2,
  "running": 1,
  "completed": 10,
  "failed": 2
}
```

---

## 🧪 Testing

```bash
# Run all tests
python test_persistence.py

# Or with pytest
pytest test_persistence.py -v -s

# Individual tests
pytest test_persistence.py::test_upsert_then_retrieve_returns_chunks -v
pytest test_persistence.py::test_delete_then_retrieve_excludes_doc -v
```

**Tests included:**
1. ✅ `test_upsert_then_retrieve_returns_chunks` - End-to-end upsert + search
2. ✅ `test_delete_then_retrieve_excludes_doc` - Deletion + rebuild + verification
3. ✅ `test_idempotent_upsert` - Duplicate detection
4. ✅ `test_health_endpoint` - Health check validation

---

## 🏗️ Architecture

### Storage Layers

```
┌─────────────────────────────────────────┐
│          FastAPI App (app_v1.py)        │
├─────────────────────────────────────────┤
│    Endpoints: upsert, delete, search    │
└─────────────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
┌──────────────┐       ┌──────────────┐
│   SQLite DB  │       │ FAISS Indices│
│  (metadata)  │       │  (vectors)   │
├──────────────┤       ├──────────────┤
│ • docs       │       │ • .faiss     │
│ • chunks     │       │   files      │
│ • indices    │       │ • atomic     │
│ • jobs       │       │   writes     │
└──────────────┘       └──────────────┘
        │
        ▼
┌──────────────┐
│    Worker    │
│  (worker.py) │
├──────────────┤
│ • ingest_docs│
│ • rebuild_   │
│   index      │
└──────────────┘
```

### Database Schema

**docs** - Document metadata
- `doc_id` (PK), `tenant_id`, `namespace`
- `doc_hash`, `embedding_version`
- `deleted_at` (soft delete)

**chunks** - Chunk data + FAISS mapping
- `chunk_id` (PK), `doc_id` (FK)
- `text`, `chunk_hash`
- `faiss_id` (maps to FAISS index)
- `deleted_at` (soft delete)

**indices** - FAISS index tracking
- `tenant_id`, `namespace`, `embedding_version` (UNIQUE)
- `faiss_path`, `ntotal`, `dimension`
- `dirty` (needs rebuild)

**jobs** - Job queue
- `job_id` (PK), `type`, `status`
- `payload_json`, `progress`, `error`

---

## 🔐 Crash Safety Guarantees

### ✅ Atomic FAISS Writes
```python
# app_v1.py + index_manager.py
1. Write to temp file: /tmp/index_xyz.faiss.tmp
2. fsync(): Force OS to flush to disk
3. os.replace(): Atomic rename (POSIX guarantee)
4. Update DB metadata in transaction
```

**Result:** Half-written indices impossible. Restart always sees last complete state.

### ✅ Idempotent Upserts
```python
# Compute doc_hash = SHA256(normalized_text)
if existing_doc.doc_hash == new_hash:
    return skipped  # No-op, no duplicates
else:
    soft_delete_old_chunks()
    insert_new_chunks()
```

**Result:** Re-uploading same doc = safe no-op. Changed content = clean update.

### ✅ Persistent Job Queue
```python
# SQLite-backed queue survives crashes
job_id = job_queue.create_job('ingest_docs', {...})
# Worker polls: SELECT * FROM jobs WHERE status='pending'
```

**Result:** Jobs survive API restarts. Worker processes after recovery.

### ✅ Deleted Chunk Filtering
```sql
-- Search query always filters
SELECT * FROM chunks 
WHERE tenant_id=? AND namespace=? 
  AND faiss_id=? 
  AND deleted_at IS NULL  -- CRITICAL
```

**Result:** Deleted chunks never returned, even before rebuild completes.

---

## 📊 Performance Notes

### Multi-tenancy
- Indices are partitioned by `(tenant_id, namespace, embedding_version)`
- Each partition = separate FAISS file
- Fast filtering via indexed queries

### Scalability
- **Reads**: FAISS in-memory, sub-millisecond search
- **Writes**: Batched embeddings, atomic swaps
- **Queue**: Single worker for P0 (can scale to multiple)

### Bottlenecks (P1+)
- SQLite concurrent writes (→ PostgreSQL/MySQL)
- Single worker (→ multiple workers + locking)
- In-memory FAISS (→ FAISS GPU or IVF indices)

---

## 🐛 Troubleshooting

### Database locked errors
```bash
# SQLite default = serialize mode, safe for single writer
# If needed, switch to PostgreSQL:
export DATABASE_URL="postgresql://user:pass@localhost/ai3_rag"
```

### Missing chunks after restart
```bash
# Check if index files exist
ls -lh ./faiss_indices/

# Verify DB state
sqlite3 ai3_rag.db "SELECT COUNT(*) FROM chunks WHERE deleted_at IS NULL;"

# Rebuild if needed
curl -X POST http://localhost:8000/v1/index/rebuild \
  -d '{"tenant_id":"acme","namespace":"proj","reembed":false}'
```

### Worker not processing jobs
```bash
# Check worker is running
ps aux | grep worker.py

# Check job queue
curl http://localhost:8000/v1/queue/stats

# Restart worker
python worker.py
```

---

## 📝 Changelog (v1.0.0)

**Added:**
- Persistent SQLite database with SQLAlchemy ORM
- FAISS index persistence with atomic writes
- Idempotent document upsert via content hashing
- Soft delete with async rebuild
- DB-backed job queue (crash-safe)
- Retrieval with deleted chunk filtering
- Comprehensive test suite (pytest)
- Health check and monitoring endpoints

**Breaking Changes from v0:**
- New API structure under `/v1/*`
- Requires database and worker setup
- Changed response schemas

---

## 🔮 Future Enhancements (P1+)

- [ ] PostgreSQL/MySQL support for production scale
- [ ] Multiple workers with distributed locking
- [ ] Hard delete (GDPR compliance)
- [ ] Index versioning and A/B testing
- [ ] Metrics/observability (Prometheus)
- [ ] Rate limiting per tenant
- [ ] Webhook notifications for job completion
- [ ] Incremental index updates (no full rebuild)
- [ ] Compression for large text fields
- [ ] Index backup and restore

---

## 📄 License

Same as parent project.

## 🤝 Contributing

Tests required for all P0 features. Run `pytest test_persistence.py` before PR.

---

**Questions?** Check existing issues or create new one with `[v1]` tag.
