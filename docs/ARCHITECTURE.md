# AI-3 Architecture - Ingestion Factory

## 🎯 DOELARCHITECTUUR - ROLE CLARITY

### AI-3 Responsibilities (Ingestion Factory)
**AI-3 DOET:**
- ✅ Document parsing (PDF, OCR, text extraction)
- ✅ Chunking (5 strategies available)
- ✅ Embeddings (BAAI/bge-m3)
- ✅ Indexing (FAISS vector store)
- ✅ Retrieval (RAG search, reranking)
- ✅ Contextual enrichment (metadata only)

**AI-3 DOET NIET:**
- ❌ Final answer generation (NO chat endpoint!)
- ❌ User-facing Q&A responses
- ❌ Data extraction for business logic
- ⚠️ UITZONDERING: Lokaal testen en fallback (als AI-4 down is)

### AI-4 Responsibilities (Intelligence Layer)
**AI-4 DOET:**
- ✅ Chat interface (user conversations)
- ✅ Data extractie (structured data from documents)
- ✅ Final answer generation (llama3.1:70b)
- ✅ Business logic en workflows
- ✅ Context building van AI-3 chunks

**FLOW:**
```
User → AI-4 (chat) → AI-3 (search) → AI-4 (generate answer) → User
```

---

## Current State (Before Refactor)

### Services
1. **DataFactory (:9000)** - app.py
   - `/v1/rag/ingest/text` - Text ingestion
   - `/v1/rag/ingest/file` - File upload ingestion  
   - `/v1/rag/search` - Vector search + reranking
   - Uses: SentenceTransformer (BAAI/bge-m3), parallel_embedder, contextual_enricher

2. **Doc Analyzer (:9100)** - doc_analyzer_service.py
   - `/analyze` - Synchronous document analysis
   - `/analyze/async` - Asynchronous with job polling
   - Uses: doc_analyzer.py → **LOCAL Ollama llama3.1:70b** ← NEEDS REROUTING

3. **Reranker (:9200)** - reranker_service.py
   - `/rerank` - Cross-encoder reranking
   - Uses: BAAI/bge-reranker-v2-m3

4. **Embedding Service (:7997)** - embedding_service.py
   - Standalone, runs on CPU (not heavily used)

### LLM Calls (To Be Rerouted)
- **doc_analyzer.py::_llm_enrich()** → http://localhost:11434 (Ollama 70B)
  - This is the MAIN target for rerouting to AI-4

## Target State (After Refactor)

### AI-4 Integration
- **All 70B LLM calls** → AI-4 http://10.0.1.227:8000/llm70/*
- **AI-3 keeps:** document analysis, chunking, embedding, reranking, vector search
- **AI-3 provides:** ONLY retrieval endpoints (search), NOT answer generation
- **AI-4 provides:** ALL final answers, chat, data extraction
- **Fallback:** If AI-4 unavailable, AI-3 can use local heuristics for testing only

### Clear Separation of Concerns
```
┌─────────────────────────────────────────────────────────────┐
│                         USER REQUEST                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │    AI-4      │  ← Chat, UI, Orchestration
                    │ (Intelligence)│
                    └──────┬───────┘
                           │
                    ┌──────▼────────────────────────────┐
                    │  1. POST /search                  │
                    │     Query → Retrieve chunks       │
                    └──────┬────────────────────────────┘
                           │
                    ┌──────▼───────┐
                    │    AI-3      │  ← Retrieval Only
                    │  (DataFactory)│
                    └──────┬───────┘
                           │
                    ┌──────▼────────────────────────────┐
                    │  Returns: Chunks + Scores         │
                    └──────┬────────────────────────────┘
                           │
                    ┌──────▼───────┐
                    │    AI-4      │  ← Answer Generation
                    │ (llama3.1:70b)│
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ FINAL ANSWER │  ← To User
                    └──────────────┘
```

### GPU Pinning
- **Embedder** → GPU 0 (CUDA_VISIBLE_DEVICES=0)
- **Reranker** → GPU 1 (CUDA_VISIBLE_DEVICES=1)
- **Workers (future)** → GPUs 2-7 (llama3.1:8b pool)

### AI-3 Endpoints (Retrieval & Indexing Only)
**Production Endpoints:**
- ✅ `GET /health` - Health check
- ✅ `POST /v1/rag/ingest/text` - Ingest text content
- ✅ `POST /v1/rag/ingest/file` - Ingest file upload
- ✅ `POST /v1/rag/search` - Vector search + reranking (RAG retrieval)
- ✅ `POST /analyze` - Document analysis (doc_analyzer service)

**Deprecated/Testing Only:**
- ⚠️ `/generate_answer` - NOT for production use (fallback only)
- ⚠️ Any LLM-based response endpoints - Route to AI-4 instead

**Schema Stability:** All endpoints maintain backward compatibility

## Configuration
See: `config/ai3_settings.py`
- AI4_LLM70_BASE_URL
- AI3_EMBED_GPU
- AI3_RERANK_GPU
- AI3_WORKER_GPUS

## Startup
See: `start_AI3_all.sh`
- Starts datafactory (:9000) with CUDA_VISIBLE_DEVICES for embedding
- Starts doc_analyzer (:9100) 
- Starts reranker (:9200) with CUDA_VISIBLE_DEVICES for reranking
