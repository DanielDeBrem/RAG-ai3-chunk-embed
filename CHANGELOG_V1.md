# Changelog - AI-3 DataFactory v1

## [1.0.0] - 2026-01-08

### 🎯 P0 Production Patches - Persistent RAG Service

Deze release transformeert AI-3 van een in-memory prototype naar een productie-ready persistent ingest/index service.

---

### ✨ Added

#### Persistence Layer
- **SQLite Database** (`models.py`)
  - Tables: `docs`, `chunks`, `indices`, `jobs`
  - SQLAlchemy ORM met relationships
  - Automatic schema creation via `init_db()`
  - Indexes op alle query-kritische kolommen

- **FAISS Index Manager** (`index_manager.py`)
  - Atomic writes: temp file → fsync → rename
  - Load/save indices from/to disk
  - Per-tenant-namespace partitioning
  - Dirty tracking voor rebuild triggers

#### API Endpoints (v1)
- `POST /v1/docs/upsert` - Synchrone document upsert (idempotent)
- `POST /v1/docs/upsert/batch` - Batch upsert met async mode
- `DELETE /v1/docs/{doc_id}` - Soft delete met rebuild job
- `POST /v1/search` - Retrieval met deleted-chunk filtering
- `POST /v1/index/rebuild` - Trigger index rebuild
- `GET /v1/jobs/{job_id}` - Job status tracking
- `GET /v1/health` - Comprehensive health check
- `GET /v1/index/stats` - Index statistieken
- `GET /v1/queue/stats` - Job queue statistieken

#### Job Queue System
- **Persistent Queue** (`job_queue.py`)
  - SQLite-backed (crash-safe)
  - Job types: `ingest_docs`, `rebuild_index`
  - Status tracking: pending → running → completed/failed
  - Progress updates (0-100%)

- **Worker Process** (`worker.py`)
  - Standalone worker executable
  - Polls database for pending jobs
  - Graceful shutdown (SIGTERM/SIGINT)
  - Configurable poll interval

#### Crash Safety Features
- ✅ **Atomic FAISS writes** - No partial index files
- ✅ **Idempotent upserts** - SHA256 content hashing
- ✅ **Soft deletes** - Data preserved, filtered from retrieval
- ✅ **Persistent jobs** - Survive API restarts

#### Testing
- **Test Suite** (`test_persistence.py`)
  - `test_upsert_then_retrieve_returns_chunks` - E2E ingestion + search
  - `test_delete_then_retrieve_excludes_doc` - Delete + rebuild verification
  - `test_idempotent_upsert` - Duplicate detection
  - `test_health_endpoint` - Health check validation
  - Uses pytest with in-memory SQLite fixtures

#### Documentation
- **README_V1.md** - Complete v1 documentation
  - Installation instructions
  - API endpoint reference met curl examples
  - Environment variables
  - Architecture diagrams
  - Crash safety guarantees
  - Troubleshooting guide
- **CHANGELOG_V1.md** - This file

#### Dependencies
- Added: `sqlalchemy`, `pytest`, `httpx`
- Updated: `requirements.txt`

---

### 🔄 Changed

#### Storage Architecture
- **Before**: In-memory `Dict[str, ProjectDocTypeIndex]`
- **After**: SQLite database + FAISS files on disk
- **Migration Path**: No automatic migration (v1 is new stack)

#### API Structure
- **Before**: `/v1/rag/ingest/text`, `/v1/rag/search`
- **After**: `/v1/docs/upsert`, `/v1/search`
- **Versioning**: All endpoints under `/v1/*`

#### Response Schemas
- Upsert responses now include `job_id` for async operations
- Search responses include `total_found` count
- Health check expanded with subsystem checks

---

### 🐛 Fixed

#### Data Loss Risks
- ❌ **Before**: Restart = all data lost
- ✅ **After**: Restart = load from persistent storage

#### Duplicate Chunks
- ❌ **Before**: Re-uploading same doc → duplicate chunks
- ✅ **After**: Content hashing → idempotent skip

#### Deleted Chunks in Search
- ❌ **Before**: No deletion support
- ✅ **After**: Soft delete + DB filtering + async rebuild

#### Crash Recovery
- ❌ **Before**: In-progress jobs lost
- ✅ **After**: Jobs persisted, resume after restart

---

### 🚀 Performance

#### Improved
- Index partitioning by tenant/namespace → faster lookups
- Atomic writes prevent corruption → no repair needed
- Batch embedding preserved (existing optimization)

#### Trade-offs
- SQLite write concurrency limit (P1: switch to PostgreSQL)
- FAISS save latency ~100-500ms (vs instant in-memory)
- Disk I/O for index loading (acceptable for P0)

---

### 📊 Database Schema

```sql
CREATE TABLE docs (
    doc_id VARCHAR(512) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    namespace VARCHAR(128) NOT NULL,
    doc_hash VARCHAR(64) NOT NULL,
    embedding_version VARCHAR(64) NOT NULL,
    deleted_at DATETIME,
    -- ... more fields
    INDEX idx_tenant_namespace (tenant_id, namespace),
    INDEX idx_deleted (deleted_at)
);

CREATE TABLE chunks (
    chunk_id VARCHAR(512) PRIMARY KEY,
    doc_id VARCHAR(512) REFERENCES docs(doc_id),
    tenant_id VARCHAR(128) NOT NULL,
    namespace VARCHAR(128) NOT NULL,
    chunk_hash VARCHAR(64) NOT NULL,
    text TEXT NOT NULL,
    faiss_id INTEGER,
    deleted_at DATETIME,
    -- ... more fields
    INDEX idx_faiss_id (faiss_id),
    INDEX idx_deleted (deleted_at)
);

CREATE TABLE indices (
    tenant_id VARCHAR(128),
    namespace VARCHAR(128),
    embedding_version VARCHAR(64),
    faiss_path VARCHAR(512) NOT NULL,
    ntotal INTEGER DEFAULT 0,
    dirty BOOLEAN DEFAULT FALSE,
    -- ... more fields
    UNIQUE (tenant_id, namespace, embedding_version)
);

CREATE TABLE jobs (
    job_id VARCHAR(64) PRIMARY KEY,
    type VARCHAR(64) NOT NULL,
    status VARCHAR(32) DEFAULT 'pending',
    payload_json TEXT NOT NULL,
    progress INTEGER DEFAULT 0,
    -- ... more fields
    INDEX idx_status (status),
    INDEX idx_type_status (type, status)
);
```

---

### 🔐 Security

#### Considerations
- Soft deletes preserve audit trail
- No authentication layer (add in P1)
- Input sanitization via Pydantic schemas
- SQL injection protection via SQLAlchemy ORM

---

### 💡 Usage Changes

#### Starting the Service

**v0 (old):**
```bash
uvicorn app:app
```

**v1 (new):**
```bash
# Terminal 1: API server
uvicorn app_v1:app --port 8000

# Terminal 2: Worker (required for async jobs)
python worker.py
```

#### Upserting Documents

**v0 (old):**
```bash
curl -X POST /v1/rag/ingest/text \
  -d '{"project_id":"proj","doc_id":"doc","text":"..."}'
```

**v1 (new):**
```bash
curl -X POST /v1/docs/upsert \
  -d '{"tenant_id":"acme","namespace":"proj","doc_id":"doc","text":"..."}'
```

#### Searching

**v0 (old):**
```bash
curl -X POST /v1/rag/search \
  -d '{"project_id":"proj","document_type":"generic","question":"..."}'
```

**v1 (new):**
```bash
curl -X POST /v1/search \
  -d '{"tenant_id":"acme","namespace":"proj","query":"..."}'
```

---

### 🧪 Testing

#### Test Coverage
- ✅ End-to-end upsert + retrieval
- ✅ Delete + rebuild + verification
- ✅ Idempotency checks
- ✅ Health check validation

#### Run Tests
```bash
pytest test_persistence.py -v -s
```

#### Test Results (Expected)
```
test_upsert_then_retrieve_returns_chunks ✅ PASSED
test_delete_then_retrieve_excludes_doc ✅ PASSED
test_idempotent_upsert ✅ PASSED
test_health_endpoint ✅ PASSED
```

---

### 📝 Breaking Changes

⚠️ **v1 is NOT backward compatible with v0**

**Migration Required:**
1. No automatic migration tool (different architecture)
2. Re-ingest all documents via new `/v1/docs/upsert` endpoint
3. Update client code to use new endpoint structure
4. Start worker process for async operations

**Compatibility:**
- Old `/v1/rag/*` endpoints still available in `app.py` (legacy)
- New `/v1/*` endpoints in `app_v1.py` (production)
- Run both during migration period (different ports)

---

### 🔮 Future (P1+)

#### Planned Enhancements
- [ ] PostgreSQL/MySQL support
- [ ] Multiple workers with locking
- [ ] Hard delete (GDPR compliance)
- [ ] Index versioning
- [ ] Prometheus metrics
- [ ] Webhook notifications
- [ ] Incremental index updates

#### Known Limitations (P0)
- Single worker only
- SQLite write concurrency
- No distributed locking
- No automatic failover
- Manual index backups

---

### 🙏 Acknowledgments

- FAISS atomic write pattern inspired by Chroma DB
- SQLAlchemy patterns from Flask-SQLAlchemy
- Job queue design simplified from Celery
- Test structure follows pytest best practices

---

### 📞 Support

- Issues: Tag with `[v1]`
- Docs: See `README_V1.md`
- Tests: Run `pytest test_persistence.py`

---

**Full Diff:** v0 (in-memory) → v1 (persistent)
- **Files Added:** 7 new files (~2000 LOC)
- **Tests Added:** 4 comprehensive tests
- **Endpoints Added:** 9 v1 endpoints
- **Dependencies Added:** 3 (sqlalchemy, pytest, httpx)

**Status:** ✅ P0 Complete - Production Ready with caveats (see limitations)
