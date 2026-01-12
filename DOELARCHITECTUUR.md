# DOELARCHITECTUUR - AI-3 en AI-4 Role Clarity

## 🎯 Kernprincipe

```
┌────────────────────────────────────────────────────────────────┐
│  AI-3 = RETRIEVAL ENGINE (parsing, chunking, embeddings)       │
│  AI-4 = INTELLIGENCE LAYER (chat, answers, data extraction)    │
└────────────────────────────────────────────────────────────────┘
```

## ✅ AI-3 Responsibilities (Ingestion Factory)

### Wat AI-3 DOET:
1. **Document Parsing**
   - PDF extractie (native + OCR)
   - Text extraction
   - Structure detection

2. **Chunking**
   - 5 strategieën beschikbaar
   - Auto-detection van beste strategie
   - Table-aware, page-aware, semantic chunking

3. **Embeddings**
   - BAAI/bge-m3 model (1024-dim)
   - Contextual enrichment met LLM
   - GPU-optimized (GPU 0)

4. **Indexing**
   - FAISS vector store
   - Multi-tenant isolation
   - Deduplication

5. **Retrieval (RAG Search)**
   - Vector similarity search
   - Reranking (BAAI/bge-reranker-v2-m3, GPU 1)
   - Top-k chunk retrieval

### Wat AI-3 NIET DOET:
- ❌ **Final answer generation**
- ❌ **Chat interfaces**
- ❌ **Data extraction voor business logic**
- ❌ **User-facing Q&A**

### Uitzondering:
- ⚠️ **Fallback mode**: Alleen voor lokaal testen als AI-4 down is
- ⚠️ **Testing**: Pipeline validatie en kwaliteitstesten

---

## ✅ AI-4 Responsibilities (Intelligence Layer)

### Wat AI-4 DOET:
1. **Chat Interface**
   - User conversations
   - Session management
   - UI/UX

2. **Final Answer Generation**
   - **ALLE antwoorden met llama3.1:70b**
   - Context building van AI-3 chunks
   - Prompt engineering

3. **Data Extraction**
   - Structured data uit documenten
   - Business logic processing
   - Workflow orchestration

4. **Integration**
   - Calls naar AI-3 voor retrieval
   - Context management
   - Error handling

### Wat AI-4 NIET DOET:
- ❌ Document parsing (laat AI-3 doen)
- ❌ Embeddings berekenen (laat AI-3 doen)
- ❌ Vector search (laat AI-3 doen)

---

## 🔄 Typische Flow

### Document Upload
```
User uploads PDF
    ↓
AI-4 ontvangt file
    ↓
AI-4 → POST /ingest (AI-3)
    ↓
AI-3: parse, chunk, embed, index
    ↓
AI-3 → returns: {chunks_added: N}
    ↓
AI-4 toont user: "✓ N chunks geïndexeerd"
```

### User Query
```
User stelt vraag
    ↓
AI-4 ontvangt query
    ↓
AI-4 → POST /search (AI-3)
    ↓
AI-3: vector search + reranking
    ↓
AI-3 → returns: [{chunk, score}, ...]
    ↓
AI-4: build context van chunks
    ↓
AI-4: generate answer met 70B
    ↓
AI-4 toont answer aan user
```

**KRITIEK:** AI-3 geeft ALLEEN chunks terug, AI-4 genereert ALTIJD het antwoord!

---

## 📋 API Endpoints

### AI-3 Endpoints (Port 9000)

**Production:**
- `POST /v1/rag/ingest/text` - Text ingestion
- `POST /v1/rag/ingest/file` - File upload ingestion
- `POST /v1/rag/search` - **Vector search + reranking (RETRIEVAL ONLY)**
- `POST /analyze` - Document analysis (port 9100)
- `GET /health` - Health check

**Deprecated/Testing Only:**
- ⚠️ `/generate_answer` - Niet voor productie (fallback/test only)
- ⚠️ Any answer generation endpoints - Route naar AI-4

### AI-4 Endpoints (Port 8000)

**Production:**
- `POST /llm70/generate` - **Final answer generation**
- `POST /llm70/extract` - Data extraction
- `POST /chat` - Chat interface
- Andere business logic endpoints

---

## 🚨 Kritieke Regels

### Regel 1: Scheiding van Verantwoordelijkheden
```
AI-3 = RETRIEVAL
AI-4 = INTELLIGENCE
```

### Regel 2: Geen Final Answers op AI-3
```python
# ❌ FOUT - AI-3 genereert answer
def search_endpoint():
    chunks = find_chunks(query)
    answer = llm.generate(chunks)  # ← FOUT!
    return answer

# ✅ GOED - AI-3 geeft alleen chunks
def search_endpoint():
    chunks = find_chunks(query)
    return chunks  # ← AI-4 doet de rest
```

### Regel 3: Alle Answers via AI-4
```python
# AI-4 code
def handle_user_query(query):
    # 1. Search AI-3
    chunks = ai3_client.search(query)
    
    # 2. Build context
    context = build_context(chunks)
    
    # 3. Generate answer (70B on AI-4)
    answer = llm70.generate(context, query)
    
    # 4. Return to user
    return answer
```

### Regel 4: Fallback Mode
```python
# AI-3 fallback (alleen voor lokaal testen)
def search_with_fallback(query):
    chunks = find_chunks(query)
    
    if AI4_AVAILABLE:
        return chunks  # ← Production flow
    else:
        # ⚠️ Fallback: Heuristic answer (geen LLM)
        return simple_answer(chunks)
```

---

## 🎨 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         USER                                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
                  ┌──────────────┐
                  │    AI-4      │
                  │  (Port 8000) │
                  │              │
                  │ - Chat UI    │
                  │ - 70B LLM    │
                  │ - Business   │
                  │   Logic      │
                  └──────┬───────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
    POST /ingest   POST /search   POST /analyze
          │              │              │
          └──────────────┼──────────────┘
                         │
                  ┌──────▼───────┐
                  │    AI-3      │
                  │  (Port 9000) │
                  │              │
                  │ - Parsing    │
                  │ - Chunking   │
                  │ - Embeddings │
                  │ - Indexing   │
                  │ - Search     │
                  │ - Reranking  │
                  └──────────────┘
                         │
                         ▼
              Returns: chunks with scores
                         │
                         ▼
                  ┌──────────────┐
                  │    AI-4      │
                  │ Generate     │
                  │ Answer (70B) │
                  └──────┬───────┘
                         │
                         ▼
                  ┌──────────────┐
                  │    USER      │
                  │  (Answer)    │
                  └──────────────┘
```

---

## 💡 Waarom Deze Scheiding?

### Voordelen:

1. **Specialization**
   - AI-3: Geoptimaliseerd voor high-throughput retrieval (8 GPU's)
   - AI-4: Geoptimaliseerd voor intelligence (70B model)

2. **Scalability**
   - AI-3 kan meerdere AI-4 instances bedienen
   - Load balancing mogelijk

3. **Maintainability**
   - Clear responsibilities
   - Makkelijker te debuggen
   - Independent updates

4. **Cost Efficiency**
   - 70B model draait alleen op AI-4 (1 server)
   - Retrieval gedistribueerd (AI-3 multi-GPU)

5. **Flexibility**
   - AI-4 kan verschillende LLM's gebruiken
   - AI-3 blijft stabiel als retrieval engine

---

## 📚 Gerelateerde Documentatie

- `ARCHITECTURE.md` - Volledige architectuur details
- `AI4_INTEGRATION_GUIDE.md` - Integratie instructies voor AI-4
- `DATAFACTORY_API_SPEC.md` - API specificaties
- `CHUNKING_STRATEGIES_README.md` - Chunking strategieën

---

## ✅ Checklist voor Implementatie

### AI-3 (Ingestion Factory)
- [x] Document parsing met OCR support
- [x] 5 chunking strategieën
- [x] Embedding service (GPU 0)
- [x] FAISS indexing
- [x] Vector search endpoint
- [x] Reranker service (GPU 1)
- [ ] Verwijder answer generation endpoints (behalve fallback)
- [ ] Update documentation

### AI-4 (Intelligence Layer)
- [ ] DataFactory client implementeren
- [ ] Document upload flow naar AI-3
- [ ] Search flow naar AI-3
- [ ] Answer generation met 70B
- [ ] Chat interface
- [ ] Error handling
- [ ] Health monitoring

---

## 🎯 Success Criteria

De architectuur is succesvol wanneer:

1. ✅ AI-3 genereert **GEEN** final answers (behalve fallback)
2. ✅ AI-4 genereert **ALLE** final answers met 70B
3. ✅ Flow: User → AI-4 → AI-3 (search) → AI-4 (answer) → User
4. ✅ AI-3 API returnt alleen chunks, niet answers
5. ✅ Clear separation of concerns
6. ✅ Documentation up to date

---

**Laatste update:** 12 januari 2026

*Deze architectuur is de doelstaat voor het RAG systeem. AI-3 en AI-4 werken samen, elk met hun eigen verantwoordelijkheid.*
