# RAG AI-3 Chunk/Embed/Rerank Services

Backend services voor de RAG pipeline op AI-3. Deze services worden aangestuurd door AI-4 (orchestrator/webgui).

## 🎯 BELANGRIJKE ARCHITECTUUR REGEL

```
┌────────────────────────────────────────────────────────────┐
│ AI-3 = RETRIEVAL ENGINE (parsing, chunking, embeddings)    │
│ AI-4 = INTELLIGENCE LAYER (chat, answers, extraction)      │
└────────────────────────────────────────────────────────────┘
```

**AI-3 DOET:**
- ✅ Document parsing, OCR, chunking
- ✅ Embeddings en indexing (FAISS)
- ✅ Vector search + reranking
- ❌ **GEEN final answer generation (behalve lokaal testen/fallback)**

**AI-4 DOET:**
- ✅ **ALLE final answers met llama3.1:70b**
- ✅ Chat interface
- ✅ Data extraction en business logic

**Flow:** `User → AI-4 → POST /search (AI-3) → chunks → AI-4 70B → answer → User`

Zie `DOELARCHITECTUUR.md` voor volledige details.

---

## 🏗️ Architectuur

```
AI-4 (Orchestrator)          AI-3 (Processing Backend)
┌─────────────────┐          ┌──────────────────────────────────┐
│ WebGUI          │          │ :9100 - Doc Analyzer             │
│ User Management │◄────────►│ :9000 - DataFactory (FAISS)      │
│ 70B Response    │          │ :8000 - Embedding Service        │
│ Generation      │          │ :9200 - Reranker Service         │
└─────────────────┘          │ :11434 - Ollama (test/fallback)  │
                             └──────────────────────────────────┘
                             
         ↑                                    ↑
         │                                    │
         └─── AI-4 genereert answers ────────┘
              AI-3 geeft alleen chunks terug
```

## 📦 Services

| Service | Poort | Functie | Model |
|---------|-------|---------|-------|
| **Doc Analyzer** | 9100 | Agentic document analysis | Llama3.1:70B via Ollama |
| **DataFactory** | 9000 | FAISS vector store + search | BAAI/bge-m3 |
| **Embedding** | 8000 | Text → Vector embeddings | BAAI/bge-m3 (CPU) |
| **Reranker** | 9200 | Cross-encoder re-ranking | BAAI/bge-reranker-v2-m3 (CUDA) |

## 🚀 Starten

### ⚡ Alle services starten (AANBEVOLEN):

```bash
./start_AI3_services.sh
```

Dit start automatisch:
- DataFactory (GPU 0, port 9000)
- Doc Analyzer (CPU, port 9100)
- Reranker (GPU 1, port 9200)
- OCR Service (GPU 2, port 9300)
- 4x Ollama instances (GPU 4-7, ports 11435-11438)

**GPU Allocatie:**
- GPU 0: DataFactory (BGE-m3 embeddings)
- GPU 1: Reranker (BGE-reranker-v2-m3)
- GPU 2: OCR Service (EasyOCR)
- GPU 3: RESERVED (future expansion)
- GPU 4-7: 4x Ollama (llama3.1:8b parallel enrichment)

### Individuele services (alleen voor testing/debugging):

```bash
# DataFactory (poort 9000, GPU 0)
CUDA_VISIBLE_DEVICES=0 uvicorn app:app --host 0.0.0.0 --port 9000

# Document Analyzer (poort 9100, CPU)
uvicorn doc_analyzer_service:app --host 0.0.0.0 --port 9100

# Reranker (poort 9200, GPU 1)
CUDA_VISIBLE_DEVICES=1 uvicorn reranker_service:app --host 0.0.0.0 --port 9200

# OCR Service (poort 9300, GPU 2)
CUDA_VISIBLE_DEVICES=2 python ocr_service.py --port 9300
```

## 📡 API Endpoints

### Document Analyzer (:9100)

```bash
# Health check
curl http://ai3:9100/health

# Analyze document
curl -X POST http://ai3:9100/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "document": "Jaarrekening 2024...",
    "filename": "jaarrekening.pdf",
    "mime_type": "application/pdf"
  }'
```

### DataFactory (:9000)

```bash
# Health check
curl http://ai3:9000/health

# Ingest document
curl -X POST http://ai3:9000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "company1",
    "project_id": "project1",
    "filename": "doc1.txt",
    "text": "Document content here..."
  }'

# Search
curl -X POST http://ai3:9000/search \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "company1",
    "project_id": "project1",
    "query": "zoek naar dit",
    "top_k": 5
  }'
```

### Embedding Service (:8000)

```bash
# Health check
curl http://ai3:8000/health

# Embed texts (via app.py endpoints)
# Wordt intern gebruikt door DataFactory
```

### Reranker (:9200)

```bash
# Health check
curl http://ai3:9200/health

# Rerank results
curl -X POST http://ai3:9200/rerank \
  -H "Content-Type: application/json" \
  -d '{
    "query": "zoek query",
    "items": [
      {"id": "1", "text": "eerste resultaat"},
      {"id": "2", "text": "tweede resultaat"}
    ],
    "top_k": 5
  }'
```

## 🔧 Configuratie

### Environment Variables

```bash
# Embedding model
export EMBED_MODEL_NAME="BAAI/bge-m3"

# Ollama voor LLM
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="llama3.1:70b"
export OLLAMA_TIMEOUT="60"

# Reranker
export RERANK_MODEL="BAAI/bge-reranker-v2-m3"
export RERANK_DEVICE="cuda"  # of "cpu"
```

## 📁 Project Structuur

```
RAG-ai3-chunk-embed/
├── app.py                    # DataFactory met FAISS + GPU management
├── datafactory_app.py        # Alternatieve DataFactory versie
├── main.py                   # Simple in-memory vector store
├── embedding_service.py      # BGE-m3 embedding service
├── doc_analyzer.py           # Agentic document analyzer
├── doc_analyzer_service.py   # FastAPI wrapper voor analyzer
├── doc_type_classifier.py    # Heuristische doc type classificatie
├── document_loader.py        # PDF/DOCX/XLSX/TXT loaders
├── meta_enricher.py          # LLM enrichment met Llama 70B
├── contextual_enricher.py    # LLM context enrichment per chunk
├── reranker.py               # BGE cross-encoder reranker
├── reranker_service.py       # FastAPI wrapper voor reranker
├── gpu_manager.py            # Hybride GPU orchestratie + cleanup
├── status_reporter.py        # Webhook status updates naar AI-4
├── analyzer_schemas.py       # Pydantic schemas voor analyzer
├── rerank_schemas.py         # Pydantic schemas voor reranker
├── models.py                 # Algemene Pydantic modellen
├── start_AI3_services.sh     # Startup script
├── requirements.txt          # Python dependencies
└── corpus/                   # Test corpus directory
```

## 🔧 GPU Management

De pipeline ondersteunt hybride GPU orchestratie:

### GPU Manager Features
- **Smart GPU Selection**: Kiest automatisch GPU met meeste vrije geheugen
- **Task Tracking**: Houdt bij welke taak actief is op welke GPU
- **Auto Cleanup**: Maakt GPU geheugen vrij na elke taak
- **Ollama Integration**: `keep_alive: 0` om modellen direct te unloaden

### Environment Variables
```bash
# Webhook naar AI-4 voor status updates
export AI4_WEBHOOK_URL="http://10.0.1.227:5001/api/webhook/ai3-status"
export WEBHOOK_ENABLED="true"

# Context enrichment model
export CONTEXT_MODEL="llama3.1:8b"
export CONTEXT_ENABLED="true"
```

### GPU Status Endpoint
```bash
# Haal GPU status op
curl http://ai3:9000/gpu/status

# Forceer GPU cleanup
curl -X POST http://ai3:9000/gpu/cleanup
```

## 📡 Status Webhooks naar AI-4

De pipeline stuurt real-time status updates naar AI-4 via webhooks:

### Verwerkingsfases
| Stage | Beschrijving | Progress % |
|-------|--------------|------------|
| `received` | Document ontvangen | 0% |
| `analyzing` | LLM document analyse | 10% |
| `chunking` | Tekst splitsen | 25% |
| `enriching` | LLM context toevoegen | 30-50% |
| `embedding` | Embeddings genereren | 50-80% |
| `storing` | Opslaan in FAISS | 85% |
| `completed` | Klaar | 100% |
| `failed` | Fout opgetreden | - |

### Webhook Payload Voorbeeld
```json
{
  "source": "ai3",
  "timestamp": "2026-01-05T14:30:00.000Z",
  "doc_id": "taxatierapport.pdf",
  "stage": "embedding",
  "progress_pct": 65,
  "message": "Embedding chunk 45/150",
  "metadata": {
    "chunks_total": 150,
    "chunks_done": 45,
    "model": "BAAI/bge-m3"
  }
}
```

## 🔄 RAG Flow

### Ingest Flow (AI-4 → AI-3)
1. AI-4 uploadt document
2. POST naar AI-3:9100/analyze → DocumentAnalysis
3. AI-4 chunked op basis van suggested_chunk_strategy
4. POST chunks naar AI-3:9000/ingest
5. AI-3 embed en opslaan in FAISS

### Query Flow (AI-4 → AI-3) ⚠️ KRITIEK
1. User query op AI-4
2. AI-4: POST query naar AI-3:9000/search (vector search)
3. AI-4: POST resultaten naar AI-3:9200/rerank
4. **AI-4: Generate answer met llama3.1:70b** ← AI-4 verantwoordelijkheid!
5. AI-4: Show answer to user

**BELANGRIJK:** AI-3 geeft ALLEEN chunks terug, AI-4 genereert het antwoord!

## 🌐 Netwerk Setup voor AI-4

AI-3 Server Details:
- **Hostname**: `principium-ai-3`
- **IP-adres (UTP/LAN)**: `10.0.1.44` ← gebruik dit voor AI-4
- **IP-adres (10GbE)**: `10.10.10.13` (directe interconnect)

Vanaf AI-4, configureer verbinding naar AI-3:

```bash
# In /etc/hosts op AI-4 (aanbevolen)
10.0.1.44  ai3 principium-ai-3

# Of gebruik directe IP's in de code
AI3_HOST = "10.0.1.44"
AI3_ANALYZER_URL = "http://10.0.1.44:9100"
AI3_DATAFACTORY_URL = "http://10.0.1.44:9000"
AI3_EMBEDDING_URL = "http://10.0.1.44:8000"
AI3_RERANKER_URL = "http://10.0.1.44:9200"
```

### Test verbinding vanaf AI-4:

```bash
# Test alle services
curl http://10.0.1.44:9100/health  # Analyzer
curl http://10.0.1.44:9000/health  # DataFactory
curl http://10.0.1.44:8000/health  # Embedding
curl http://10.0.1.44:9200/health  # Reranker
```

## 📋 Dependencies

```bash
pip install -r requirements.txt
```

Belangrijkste packages:
- fastapi + uvicorn
- sentence-transformers
- faiss-cpu
- torch
- pypdf, python-docx, openpyxl

---

## 📚 Documentatie

**Core Docs (in `docs/`):**
- **`docs/DOELARCHITECTUUR.md`** - Volledige uitleg van AI-3/AI-4 scheiding
- **`docs/ARCHITECTURE.md`** - Technische architectuur details
- **`docs/OPERATIONS.md`** - Deployment, GPU allocation, monitoring
- **`docs/API_REFERENCE.md`** - Complete API specificaties
- **`docs/CHUNKING_GUIDE.md`** - Chunking strategieën
- **`docs/AI4_INTEGRATION_GUIDE.md`** - Integratie instructies voor AI-4
- **`docs/CHANGELOG.md`** - Version history

**Tests:** Alle test files staan in `tests/`

---

**Laatste update:** 14 januari 2026
