# AI-3 Ingestion Factory - Refactor Complete

## Overview

AI-3 is nu een **stabiele ingestion factory** met:
- ✅ **70B LLM routing naar AI-4** via HTTP
- ✅ **GPU pinning** voor embedder (GPU 0) en reranker (GPU 1)
- ✅ **Fallback heuristics** als AI-4 niet bereikbaar
- ✅ **Stabiele endpoints** voor AI-4 orchestrator
- ✅ **GPU's 2-7 vrij** voor toekomstige worker pool (llama3.1:8b)

## Architecture

```
AI-3 (10.0.1.226)
├── DataFactory (:9000)        GPU 0 - Embedder (BAAI/bge-m3)
├── Doc Analyzer (:9100)       → AI-4 - LLM70 routing
└── Reranker (:9200)           GPU 1 - Reranker (bge-reranker-v2-m3)

AI-4 (10.0.1.227:8000)
└── LLM70 Endpoints
    ├── /llm70/health
    ├── /llm70/warmup
    └── /llm70/chat      ← 70B analysis from AI-3
```

## What Changed

### 1. Configuration System
**File:** `config/ai3_settings.py`

Nieuwe environment variables:
```bash
# AI-4 Integration
AI4_LLM70_BASE_URL=http://10.0.1.227:8000
AI4_LLM70_ENABLED=true
AI4_LLM70_TIMEOUT=180
AI4_FALLBACK_TO_HEURISTICS=true

# GPU Pinning
AI3_EMBED_GPU=0
AI3_RERANK_GPU=1
AI3_WORKER_GPUS=2,3,4,5,6,7
```

### 2. LLM70 Client
**File:** `llm70_client.py`

Nieuwe client voor AI-4 communicatie:
- `warmup()` - Warm up AI-4 LLM
- `chat()` - Generic chat met context
- `analyze_document()` - Document analyse specifiek
- Auto-retry en error handling
- Connection pooling

### 3. Doc Analyzer Refactor
**File:** `doc_analyzer.py`

**VOOR:**
```python
# Direct Ollama call op AI-3
requests.post("http://localhost:11434/v1/chat/completions")
```

**NA:**
```python
# Route naar AI-4
llm_client = get_llm70_client()
result = llm_client.analyze_document(document, filename, mime_type)

# Fallback naar heuristics bij connection errors
if AI4_FALLBACK_TO_HEURISTICS:
    return _llm_enrich_heuristic(document, filename, mime_type)
```

### 4. GPU Pinning
**File:** `start_AI3_all.sh`

Services starten met `CUDA_VISIBLE_DEVICES`:
```bash
# DataFactory - GPU 0
CUDA_VISIBLE_DEVICES=0 python3 -m uvicorn app:app --port 9000

# Reranker - GPU 1  
CUDA_VISIBLE_DEVICES=1 python3 -m uvicorn reranker_service:app --port 9200

# Doc Analyzer - Geen GPU (gebruikt AI-4)
python3 -m uvicorn doc_analyzer_service:app --port 9100
```

### 5. Endpoint Stability
Alle endpoints blijven ongewijzigd - **backward compatible**:

**DataFactory (:9000)**
- ✅ `GET /health`
- ✅ `POST /v1/rag/ingest/text`
- ✅ `POST /v1/rag/ingest/file`
- ✅ `POST /v1/rag/search`

**Doc Analyzer (:9100)**
- ✅ `GET /health`
- ✅ `POST /analyze`
- ✅ `POST /analyze/async`
- ✅ `GET /analyze/status/{job_id}`

**Reranker (:9200)**
- ✅ `GET /health`
- ✅ `POST /rerank`

## Quick Start

### 1. Start Services
```bash
./start_AI3_all.sh
```

Dit start:
- DataFactory op :9000 (met GPU 0)
- Doc Analyzer op :9100 (routes naar AI-4)
- Reranker op :9200 (met GPU 1)

### 2. Run Tests
```bash
./test_AI3_complete.sh
```

Test suite omvat:
- Health checks
- Doc analyzer (met AI-4 routing)
- Ingest met verschillende chunking strategies
- Search met reranking
- GPU status monitoring
- Volledige integration test (analyze → ingest → search)

### 3. Monitor
```bash
# Logs
tail -f logs/datafactory.log
tail -f logs/doc_analyzer.log
tail -f logs/reranker.log

# GPU status
curl http://localhost:9000/gpu/status
curl http://localhost:9100/gpu/status
```

## Testing AI-4 Integration

### Test 1: Health Check
```bash
curl http://localhost:9100/health
```

### Test 2: Analyze Document (Routes naar AI-4)
```bash
curl -X POST http://localhost:9100/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "document": "Dit is een jaarrekening voor 2024...",
    "filename": "jaarrekening.pdf",
    "mime_type": "application/pdf"
  }'
```

**Response bevat:**
```json
{
  "analysis": {
    "document_type": "annual_report_pdf",
    "main_entities": ["Camping de Brem BV", ...],
    "main_topics": ["balans", "winst", ...],
    "extra": {
      "llm_notes": "parsed_by_ai4_llama3_70b"  ← AI-4!
    }
  }
}
```

### Test 3: Fallback Test (Simuleer AI-4 down)
```bash
# Disable AI-4
export AI4_LLM70_ENABLED=false

# Start services
./start_AI3_all.sh

# Test analyze - moet heuristic fallback gebruiken
curl -X POST http://localhost:9100/analyze \
  -H 'Content-Type: application/json' \
  -d '{"document": "test", "filename": "test.txt"}'
```

**Response bevat:**
```json
{
  "extra": {
    "llm_notes": "heuristic_fallback"  ← Fallback!
  }
}
```

## Integration with AI-4

### AI-4 Moet Implementeren

**Endpoint:** `POST /llm70/chat`

**Request:**
```json
{
  "question": "Bestandsnaam: test.pdf\nMIME type: application/pdf\n\nCONTENT BEGIN:\n...",
  "system": "Je bent een document-analyzer. Geef een korte JSON met...",
  "temperature": 0.1,
  "max_tokens": 512
}
```

**Response:**
```json
{
  "response": "{\"domain\": \"finance\", \"format_hint\": \"pdf\", \"entities\": [...], \"topics\": [...]}"
}
```

### Testing van AI-4
Vanaf AI-4 kun je AI-3 testen:

```bash
# Van AI-4 → AI-3 ingest
curl -X POST http://10.0.1.226:9000/v1/rag/ingest/text \
  -H 'Content-Type: application/json' \
  -d '{
    "project_id": "test",
    "document_type": "generic",
    "doc_id": "doc001",
    "text": "Test document tekst...",
    "metadata": {"source": "ai4_orchestrator"}
  }'

# Van AI-4 → AI-3 search
curl -X POST http://10.0.1.226:9000/v1/rag/search \
  -H 'Content-Type: application/json' \
  -d '{
    "project_id": "test",
    "document_type": "generic", 
    "question": "Wat is de inhoud?",
    "top_k": 5
  }'
```

## Configuration Options

### Enable/Disable AI-4 Routing
```bash
# Gebruik AI-4 (default)
export AI4_LLM70_ENABLED=true

# Disable AI-4 (gebruik alleen heuristics)
export AI4_LLM70_ENABLED=false
```

### Configure Fallback Behavior
```bash
# Enable fallback naar heuristics (default)
export AI4_FALLBACK_TO_HEURISTICS=true

# Disable fallback (return errors bij AI-4 failure)
export AI4_FALLBACK_TO_HEURISTICS=false
```

### Change GPU Assignments
```bash
# Embedder op GPU 2 ipv 0
export AI3_EMBED_GPU=2

# Reranker op GPU 3 ipv 1
export AI3_RERANK_GPU=3

# Worker pool GPU's
export AI3_WORKER_GPUS=0,1,4,5,6,7
```

### AI-4 Connection Settings
```bash
# Change AI-4 URL
export AI4_LLM70_BASE_URL=http://10.0.1.227:8000

# Increase timeout voor grote documenten
export AI4_LLM70_TIMEOUT=300
```

## Performance & Monitoring

### GPU Usage
```bash
# Check welke GPU's gebruikt worden
nvidia-smi

# Expected:
# GPU 0: ~2-3GB (embedder - BAAI/bge-m3)
# GPU 1: ~2-3GB (reranker - bge-reranker-v2-m3)
# GPU 2-7: Vrij (beschikbaar voor worker pool)
```

### Service Health
```bash
# All services
curl http://localhost:9000/health  # DataFactory
curl http://localhost:9100/health  # Doc Analyzer
curl http://localhost:9200/health  # Reranker

# GPU status per service
curl http://localhost:9000/gpu/status
curl http://localhost:9100/gpu/status
```

### Logs
```bash
# Real-time monitoring
tail -f logs/*.log

# Search for errors
grep -i error logs/*.log

# Check AI-4 calls
grep "AI-4 LLM70" logs/doc_analyzer.log
```

## Troubleshooting

### AI-4 Connection Errors
**Symptoom:** Doc analyzer logs tonen "AI-4 unavailable"

**Fix:**
```bash
# Check AI-4 reachable
curl http://10.0.1.227:8000/llm70/health

# Check network
ping 10.0.1.227

# Check fallback is enabled
grep "FALLBACK" logs/doc_analyzer.log

# Als fallback enabled: heuristics worden gebruikt, geen probleem
# Als fallback disabled: enable met export AI4_FALLBACK_TO_HEURISTICS=true
```

### GPU Out of Memory
**Symptoom:** "CUDA out of memory" in logs

**Fix:**
```bash
# Check GPU usage
nvidia-smi

# Als GPU 0 vol:
# 1. Check dat alleen embedder op GPU 0 draait
# 2. Restart services: pkill -f uvicorn && ./start_AI3_all.sh

# Als persistent: verklein batch sizes in app.py
export PARALLEL_EMBED_ENABLED=false  # Disable parallel embedding
```

### Services Won't Start
**Symptoom:** Start script faalt

**Fix:**
```bash
# Check ports vrij
netstat -tulpn | grep -E '9000|9100|9200'

# Kill oude processen
pkill -f 'uvicorn.*9000'
pkill -f 'uvicorn.*9100'
pkill -f 'uvicorn.*9200'

# Check Python environment
python3 -c "import fastapi, torch, sentence_transformers"

# Reinstall als nodig
pip install -r requirements.txt
```

### Search Returns No Results
**Symptoom:** `/v1/rag/search` returns empty chunks

**Fix:**
```bash
# Check of er data geïngested is
curl -s http://localhost:9000/gpu/status | jq '.indices'

# Test ingest eerst
curl -X POST http://localhost:9000/v1/rag/ingest/text \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "test", "doc_id": "test1", "text": "Test tekst", "document_type": "generic"}'

# Check logs
tail -f logs/datafactory.log
```

## Next Steps (Not Implemented Yet)

### Worker Pool (llama3.1:8b)
GPU's 2-7 zijn vrij voor een worker pool:

```bash
# TODO: Implementeer parallel 8B worker pool
# - Start 6x llama3.1:8b op GPU 2-7
# - Load balancing over workers
# - Queue system voor tasks
```

### Advanced Features
- Persistent storage (SQLite/PostgreSQL voor indices)
- Advanced caching (Redis)
- Metrics & monitoring (Prometheus/Grafana)
- A/B testing tussen AI-4 en local LLM
- Rate limiting per project

## File Structure

```
RAG-ai3-chunk-embed/
├── config/
│   └── ai3_settings.py          ← Configuration
├── llm70_client.py              ← AI-4 client
├── doc_analyzer.py              ← Refactored (AI-4 routing)
├── app.py                       ← DataFactory (unchanged)
├── doc_analyzer_service.py      ← Service (unchanged)
├── reranker.py                  ← Reranker (unchanged)
├── start_AI3_all.sh             ← Startup script (GPU pinning)
├── test_AI3_complete.sh         ← Test suite
├── logs/                        ← Service logs
│   ├── datafactory.log
│   ├── doc_analyzer.log
│   └── reranker.log
├── ARCHITECTURE.md              ← Architecture overview
└── README_AI3_REFACTOR.md       ← This file
```

## Summary

**✅ Done:**
1. Config systeem voor AI-4 routing en GPU pinning
2. LLM70 client voor AI-4 communicatie
3. Doc analyzer reroute naar AI-4 met fallback
4. GPU pinning voor embedder (GPU 0) en reranker (GPU 1)
5. Startup script met proper CUDA_VISIBLE_DEVICES
6. Comprehensive test suite
7. Endpoints blijven stabiel (backward compatible)

**🔄 Ready for Testing:**
- Start services met `./start_AI3_all.sh`
- Run tests met `./test_AI3_complete.sh`
- AI-4 kan nu AI-3 endpoints aanroepen
- Doc analyzer routes 70B calls naar AI-4

**🚀 Next (After Testing):**
- Implementeer worker pool op GPU's 2-7
- llama3.1:8b voor snelle queries
- Load balancing tussen workers

## Contact & Support

**Logs:** `tail -f logs/*.log`  
**GPU Status:** `nvidia-smi -l 1`  
**Service Status:** `curl http://localhost:{9000,9100,9200}/health`

---

**Last Updated:** 2026-01-08  
**Version:** 1.0.0 (Refactor Complete)
