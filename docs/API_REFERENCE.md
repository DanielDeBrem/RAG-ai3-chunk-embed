# RAG DataFactory API Specification
## Complete API Reference voor AI-4 Integratie

**Versie:** 0.5.0  
**Base URL:** `http://localhost:9000` (AI-3 server)  
**OpenAPI Docs:** `http://localhost:9000/docs`  
**OpenAPI JSON:** `http://localhost:9000/openapi.json`

---

## 📋 Service Overview

### Running Services
```bash
Port 9000: DataFactory (app.py) - Main API
Port 9100: Document Analyzer Service
Port 9200: Reranker Service
```

### Health Check
```bash
curl http://localhost:9000/health
```

**Response:**
```json
{
  "status": "ok",
  "detail": "ai-3 datafactory up"
}
```

---

## 🔌 API Endpoints

### 1. POST /ingest
**Description:** Simplified ingest endpoint voor AI-4 orchestrator

**URL:** `http://localhost:9000/ingest`

**Method:** POST

**Content-Type:** application/json

**Request Body:**
```json
{
  "tenant_id": "string",           // REQUIRED
  "project_id": "string",          // REQUIRED
  "filename": "string",            // REQUIRED
  "text": "string",                // REQUIRED
  "user_id": "string",             // OPTIONAL
  "mime_type": "string",           // OPTIONAL (e.g., "application/pdf")
  "document_type": "string",       // OPTIONAL (default: "generic")
  "metadata": {},                  // OPTIONAL (any JSON object)
  "chunk_strategy": "string",      // OPTIONAL (see strategies below)
  "chunk_overlap": 0               // OPTIONAL (default: 0)
}
```

**Response 200:**
```json
{
  "project_id": "tenant:project",
  "document_type": "generic",
  "doc_id": "filename.pdf",
  "chunks_added": 5
}
```

**Response 422:** Validation Error
```json
{
  "detail": [
    {
      "loc": ["body", "tenant_id"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

**Example cURL:**
```bash
curl -X POST "http://localhost:9000/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "project_id": "docs_001",
    "filename": "test.pdf",
    "text": "This is a test document with some content.",
    "document_type": "generic",
    "chunk_strategy": "default"
  }'
```

**Processing Details:**
- Automatic OCR for scanned PDFs
- Automatic chunking strategy selection (if not specified)
- Contextual enrichment (6x parallel GPU)
- High-quality embeddings (BGE-m3, 1024-dim)
- Deduplication
- Processing time: 1-2s (small), 30-60s (medium), 5-10min (large 45MB+)

---

### 2. POST /search
**Description:** Simplified search endpoint voor AI-4 orchestrator

**URL:** `http://localhost:9000/search`

**Method:** POST

**Content-Type:** application/json

**Request Body:**
```json
{
  "tenant_id": "string",           // REQUIRED
  "project_id": "string",          // REQUIRED
  "query": "string",               // REQUIRED (or use "question")
  "question": "string",            // OPTIONAL (alias for "query")
  "user_id": "string",             // OPTIONAL
  "document_type": "string",       // OPTIONAL (default: "generic")
  "top_k": 5                       // OPTIONAL (default: 5)
}
```

**Response 200:**
```json
{
  "chunks": [
    {
      "doc_id": "test.pdf",
      "chunk_id": "test.pdf#c0000",
      "text": "Chunk content here...",
      "score": 0.95,
      "metadata": {
        "tenant_id": "acme",
        "project_id": "docs_001",
        "document_type": "generic",
        "raw_text": "Original chunk...",
        "embed_text": "Enriched chunk...",
        "context_enriched": true,
        "chunk_strategy": "default"
      }
    }
  ]
}
```

**Response 404:** Index Not Found
```json
{
  "detail": "Index voor project_id='tenant:project' document_type='generic' niet gevonden"
}
```

**Example cURL:**
```bash
curl -X POST "http://localhost:9000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "project_id": "docs_001",
    "query": "What is this document about?",
    "top_k": 5
  }'
```

**Processing Details:**
- Vector similarity search (FAISS)
- Automatic reranking if reranker service available (port 9200)
- Fallback to vector scores if reranker fails
- Returns top_k most relevant chunks

---

### 3. GET /health
**Description:** Health check endpoint

**URL:** `http://localhost:9000/health`

**Method:** GET

**Response 200:**
```json
{
  "status": "ok",
  "detail": "ai-3 datafactory up"
}
```

**Example cURL:**
```bash
curl "http://localhost:9000/health"
```

---

### 4. GET /gpu/status
**Description:** Monitor GPU usage for debugging

**URL:** `http://localhost:9000/gpu/status`

**Method:** GET

**Response 200:**
```json
{
  "gpus": [
    {
      "id": 0,
      "name": "NVIDIA GeForce RTX 4090",
      "memory_total_mb": 24000,
      "memory_used_mb": 2500,
      "memory_free_mb": 21500,
      "utilization_percent": 15,
      "temperature_c": 45
    }
  ],
  "timestamp": "2026-01-12T11:00:00Z"
}
```

**Example cURL:**
```bash
curl "http://localhost:9000/gpu/status"
```

---

### 5. GET /embedder/status
**Description:** Check embedding model status

**URL:** `http://localhost:9000/embedder/status`

**Method:** GET

**Response 200:**
```json
{
  "model_loaded": true,
  "model_name": "BAAI/bge-m3",
  "device": "cuda:0",
  "dedicated_gpu": "GPU 0 (via CUDA_VISIBLE_DEVICES)"
}
```

**Example cURL:**
```bash
curl "http://localhost:9000/embedder/status"
```

---

### 6. POST /embedder/unload
**Description:** Unload embedding model to free GPU memory

**URL:** `http://localhost:9000/embedder/unload`

**Method:** POST

**Response 200:**
```json
{
  "status": "ok",
  "message": "Embedding model unloaded, GPU memory freed"
}
```

**Example cURL:**
```bash
curl -X POST "http://localhost:9000/embedder/unload"
```

---

### 7. POST /gpu/cleanup
**Description:** Force GPU memory cleanup

**URL:** `http://localhost:9000/gpu/cleanup`

**Method:** POST

**Response 200:**
```json
{
  "status": "ok",
  "message": "GPU cleanup completed"
}
```

**Example cURL:**
```bash
curl -X POST "http://localhost:9000/gpu/cleanup"
```

---

## 🎯 Chunking Strategies

### Available Strategies

| Strategy | Use Case | Max Chars | Overlap | Auto-Detect |
|----------|----------|-----------|---------|-------------|
| `default` | Normal text, articles | 800 | 0 | 0.3 (fallback) |
| `page_plus_table_aware` | PDFs with pages | 1500 | 200 | 0.95 |
| `semantic_sections` | Markdown, headers | 1200 | 150 | 0.85 |
| `conversation_turns` | Chats, messaging | 600 | 0 | 0.90 |
| `table_aware` | Data with tables | 1000 | 100 | 0.85 |

### Auto-Detection

**Strategy selection happens automatically based on:**
- Content type (PDF, chat patterns, etc.)
- Structural markers ([PAGE X], headers, speaker patterns)
- File metadata (filename, mime_type)

**Detection triggers:**
- `[PAGE` in text → `page_plus_table_aware` (0.95 confidence)
- 5+ speaker patterns → `conversation_turns` (0.90 confidence)
- 2+ markdown headers → `semantic_sections` (0.85 confidence)
- 3+ table rows → `table_aware` (0.85 confidence)
- Default fallback → `default` (0.30 confidence)

### Specify Strategy

**In /ingest request:**
```json
{
  "chunk_strategy": "page_plus_table_aware",
  "chunk_overlap": 200
}
```

**Omit for auto-detection:**
```json
{
  // chunk_strategy not specified → auto-detect
}
```

---

## 🔑 Project/Tenant Format

### Internal Format
Internally, DataFactory combines tenant_id and project_id:
```
internal_project_id = "tenant_id:project_id"
```

### Request Format (AI-4 → AI-3)
**Separate parameters in request body:**
```json
{
  "tenant_id": "acme",
  "project_id": "docs_001"
}
```

### Response Format (AI-3 → AI-4)
**Combined format in response:**
```json
{
  "project_id": "acme:docs_001"
}
```

### Index Key
Indices are stored as:
```
index_key = "tenant_id:project_id::document_type"
Example: "acme:docs_001::generic"
```

---

## 📝 Complete Usage Flow

### Step 1: Health Check
```bash
curl "http://localhost:9000/health"
```

**Expected:**
```json
{"status": "ok", "detail": "ai-3 datafactory up"}
```

---

### Step 2: Ingest Document
```bash
curl -X POST "http://localhost:9000/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "project_id": "test_project",
    "filename": "sample.pdf",
    "text": "This is a sample document about RAG systems. It contains information about vector embeddings and semantic search.",
    "document_type": "generic"
  }'
```

**Expected Response:**
```json
{
  "project_id": "demo:test_project",
  "document_type": "generic",
  "doc_id": "sample.pdf",
  "chunks_added": 2
}
```

---

### Step 3: Search Query
```bash
curl -X POST "http://localhost:9000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "project_id": "test_project",
    "query": "What is this document about?",
    "document_type": "generic",
    "top_k": 3
  }'
```

**Expected Response:**
```json
{
  "chunks": [
    {
      "doc_id": "sample.pdf",
      "chunk_id": "sample.pdf#c0000",
      "text": "This is a sample document about RAG systems...",
      "score": 0.87,
      "metadata": {
        "tenant_id": "demo",
        "project_id": "test_project",
        "document_type": "generic"
      }
    }
  ]
}
```

---

## 🚨 Error Handling

### HTTP Status Codes

| Code | Meaning | Response |
|------|---------|----------|
| 200 | Success | Normal response |
| 404 | Not Found | Index not found, document not found |
| 422 | Validation Error | Invalid request parameters |
| 500 | Server Error | Internal processing error |

### Common Errors

**404 - Index Not Found:**
```json
{
  "detail": "Index voor project_id='demo:test' document_type='generic' niet gevonden"
}
```
**Solution:** Ingest documents first before searching

**422 - Validation Error:**
```json
{
  "detail": [
    {
      "loc": ["body", "tenant_id"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```
**Solution:** Include all required fields

**500 - Internal Error:**
```json
{
  "detail": "Processing error: [error details]"
}
```
**Solution:** Check logs, retry, or contact support

---

## ⏱️ Timeouts & Performance

### Processing Times
- **Small docs (1-2MB):** 30-60 seconds
- **Medium docs (5-10MB):** 2-3 minutes
- **Large docs (45MB+):** 5-10 minutes

### Recommended Timeouts
```python
INGEST_TIMEOUT = 600  # 10 minutes
SEARCH_TIMEOUT = 30   # 30 seconds
HEALTH_TIMEOUT = 5    # 5 seconds
```

### Throughput
- **Processing:** ~5 MB/min
- **Search:** < 1 second
- **Concurrent requests:** Supported (async)

---

## 🔐 Authentication

**Current:** None (internal network)

**Future:** Consider adding:
- API keys
- JWT tokens
- IP whitelist

---

## 📚 Additional Services

### Document Analyzer Service (Port 9100)
```bash
# Health check
curl "http://localhost:9100/health"

# Analyze document
curl -X POST "http://localhost:9100/analyze" \
  -H "Content-Type: application/json" \
  -d '{"text": "Document content..."}'
```

### Reranker Service (Port 9200)
```bash
# Health check
curl "http://localhost:9200/health"

# Rerank chunks
curl -X POST "http://localhost:9200/rerank" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "search query",
    "items": [{"id": "1", "text": "chunk 1"}],
    "top_k": 5
  }'
```

---

## 🧪 Testing

### Quick Test Script
```bash
#!/bin/bash

# 1. Health check
echo "=== Health Check ==="
curl -s "http://localhost:9000/health" | jq

# 2. Ingest test document
echo -e "\n=== Ingest Document ==="
curl -s -X POST "http://localhost:9000/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "test",
    "project_id": "api_test",
    "filename": "test.txt",
    "text": "This is a test document for API validation."
  }' | jq

# 3. Search test
echo -e "\n=== Search Query ==="
curl -s -X POST "http://localhost:9000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "test",
    "project_id": "api_test",
    "query": "What is this about?",
    "top_k": 2
  }' | jq

echo -e "\n=== Test Complete ==="
```

---

## 📖 Python Client Example

```python
import requests
import time

class DataFactoryClient:
    def __init__(self, base_url="http://localhost:9000", timeout=600):
        self.base_url = base_url
        self.timeout = timeout
    
    def health_check(self):
        """Check if service is running."""
        try:
            r = requests.get(f"{self.base_url}/health", timeout=5)
            return r.status_code == 200
        except:
            return False
    
    def ingest(self, tenant_id, project_id, filename, text, **kwargs):
        """Ingest document."""
        payload = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "filename": filename,
            "text": text,
            **kwargs
        }
        r = requests.post(
            f"{self.base_url}/ingest",
            json=payload,
            timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()
    
    def search(self, tenant_id, project_id, query, top_k=5, **kwargs):
        """Search for chunks."""
        payload = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "query": query,
            "top_k": top_k,
            **kwargs
        }
        r = requests.post(
            f"{self.base_url}/search",
            json=payload,
            timeout=30
        )
        r.raise_for_status()
        return r.json()

# Usage
client = DataFactoryClient()

# Health check
if not client.health_check():
    print("ERROR: DataFactory not responding!")
    exit(1)

# Ingest
result = client.ingest(
    tenant_id="demo",
    project_id="test",
    filename="doc.pdf",
    text="Sample content..."
)
print(f"Ingested {result['chunks_added']} chunks")

# Search
search_result = client.search(
    tenant_id="demo",
    project_id="test",
    query="What is this about?"
)
for chunk in search_result["chunks"]:
    print(f"Score {chunk['score']:.2f}: {chunk['text'][:100]}...")
```

---

## 📞 Support & Troubleshooting

### Check Logs
```bash
tail -f ~/Projects/RAG-ai3-chunk-embed/logs/datafactory_test.log
```

### Restart Services
```bash
cd ~/Projects/RAG-ai3-chunk-embed
./start_AI3_services.sh
```

### Stop Services
```bash
pkill -f "uvicorn.*9000"
pkill -f "uvicorn.*9100"
pkill -f "uvicorn.*9200"
```

---

**Last Updated:** 2026-01-12  
**Version:** 0.5.0  
**Maintained by:** AI-3 RAG DataFactory Team
