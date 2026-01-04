# RAG AI-3 Chunk/Embed/Rerank Services

Backend services voor de RAG pipeline op AI-3. Deze services worden aangestuurd door AI-4 (orchestrator/webgui).

## 🏗️ Architectuur

```
AI-4 (Orchestrator)          AI-3 (Processing Backend)
┌─────────────────┐          ┌──────────────────────────────────┐
│ WebGUI          │          │ :9100 - Doc Analyzer (Llama 70B) │
│ User Management │◄────────►│ :9000 - DataFactory (FAISS)      │
│ 70B Response    │          │ :8000 - Embedding Service        │
│ Generation      │          │ :9200 - Reranker Service         │
└─────────────────┘          │ :11434 - Ollama (Llama3.1:70B)   │
                             └──────────────────────────────────┘
```

## 📦 Services

| Service | Poort | Functie | Model |
|---------|-------|---------|-------|
| **Doc Analyzer** | 9100 | Agentic document analysis | Llama3.1:70B via Ollama |
| **DataFactory** | 9000 | FAISS vector store + search | BAAI/bge-m3 |
| **Embedding** | 8000 | Text → Vector embeddings | BAAI/bge-m3 (CPU) |
| **Reranker** | 9200 | Cross-encoder re-ranking | BAAI/bge-reranker-v2-m3 (CUDA) |

## 🚀 Starten

### Alle services starten:

```bash
./start_AI3_services.sh
```

### Individuele services:

```bash
# Embedding service (poort 8000)
uvicorn embedding_service:app --host 0.0.0.0 --port 8000

# DataFactory (poort 9000)
uvicorn app:app --host 0.0.0.0 --port 9000

# Document Analyzer (poort 9100)
uvicorn doc_analyzer_service:app --host 0.0.0.0 --port 9100

# Reranker (poort 9200)
uvicorn reranker_service:app --host 0.0.0.0 --port 9200
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
├── app.py                    # DataFactory met FAISS
├── datafactory_app.py        # Alternatieve DataFactory versie
├── main.py                   # Simple in-memory vector store
├── embedding_service.py      # BGE-m3 embedding service
├── doc_analyzer.py           # Agentic document analyzer
├── doc_analyzer_service.py   # FastAPI wrapper voor analyzer
├── doc_type_classifier.py    # Heuristische doc type classificatie
├── document_loader.py        # PDF/DOCX/XLSX/TXT loaders
├── meta_enricher.py          # LLM enrichment met Llama 70B
├── reranker.py               # BGE cross-encoder reranker
├── reranker_service.py       # FastAPI wrapper voor reranker
├── analyzer_schemas.py       # Pydantic schemas voor analyzer
├── rerank_schemas.py         # Pydantic schemas voor reranker
├── models.py                 # Algemene Pydantic modellen
├── start_AI3_services.sh     # Startup script
├── requirements.txt          # Python dependencies
└── corpus/                   # Test corpus directory
```

## 🔄 RAG Flow

### Ingest Flow (AI-4 → AI-3)
1. AI-4 uploadt document
2. POST naar AI-3:9100/analyze → DocumentAnalysis
3. AI-4 chunked op basis van suggested_chunk_strategy
4. POST chunks naar AI-3:9000/ingest
5. AI-3 embed en opslaan in FAISS

### Query Flow (AI-4 → AI-3)
1. User query op AI-4
2. POST query naar AI-3:9000/search (vector search)
3. POST resultaten naar AI-3:9200/rerank
4. AI-4 gebruikt top results voor response generation

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
