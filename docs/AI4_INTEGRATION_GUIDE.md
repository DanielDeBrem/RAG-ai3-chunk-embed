# AI-4 Integration Guide - DataFactory API Usage

## 🎯 BELANGRIJKE ARCHITECTUUR REGEL

### Role Clarity
```
┌─────────────────────────────────────────────────────────┐
│ AI-3 = RETRIEVAL ENGINE (parsing, chunking, embeddings) │
│ AI-4 = INTELLIGENCE LAYER (chat, answers, extraction)   │
└─────────────────────────────────────────────────────────┘
```

**AI-3 (DataFactory) DOET:**
- ✅ Document parsing, OCR, chunking
- ✅ Embeddings en indexing (FAISS)
- ✅ Vector search + reranking (RAG retrieval)
- ❌ **GEEN final answers genereren**
- ❌ **GEEN chat interface**
- ❌ **GEEN data extractie voor business logic**

**AI-4 (Jouw Server) DOET:**
- ✅ Chat interface met gebruikers
- ✅ **Final answer generation met llama3.1:70b**
- ✅ Data extractie en business logic
- ✅ Context building van AI-3 chunks

**KRITIEKE FLOW:**
```
User vraag → AI-4 → POST /search (AI-3) → chunks → AI-4 70B → answer → User
```

**AI-3 geeft ALLEEN chunks terug, NOOIT final answers!**

---

## 📋 Instructie Voor Cline Op AI-4

**Kopieer dit naar Cline op AI-4:**

---

## RAG DataFactory Integration (AI-3 Server)

Je hebt toegang tot een high-performance RAG DataFactory op **AI-3 server** voor document processing en vector search.

**LET OP:** AI-3 is een RETRIEVAL ENGINE, geen answer generator. Jij (AI-4) bent verantwoordelijk voor alle final answers met je 70B model.

### 🔌 API Endpoints

**Base URL:** `http://AI-3-IP-ADDRESS:9000`

*(Vervang AI-3-IP-ADDRESS met het echte IP van de AI-3 server)*

---

### 📤 1. Document Ingest API

**Endpoint:** `POST /ingest`

Upload en process een document (met automatische OCR, chunking, enrichment en embedding).

**Request:**
```json
{
  "tenant_id": "string",           // Tenant identifier
  "project_id": "string",          // Project identifier  
  "user_id": "string",             // User identifier (optional)
  "filename": "string",            // Document filename
  "mime_type": "string",           // MIME type (e.g., "application/pdf")
  "text": "string",                 // Extracted text content
  "document_type": "string",       // Type hint (optional, auto-detected)
  "metadata": {},                  // Extra metadata (optional)
  "chunk_strategy": "string",      // Chunking strategy (optional)
  "chunk_overlap": 0               // Overlap in chars (optional)
}
```

**Available chunk_strategy options:**
- `"default"` - Standard paragraph-based (800 chars)
- `"page_plus_table_aware"` - Respects page boundaries & tables (PDF's)
- `"semantic_sections"` - Splits on headers/sections
- `"conversation_turns"` - Splits on dialogue turns (chatlogs)
- `"table_aware"` - Preserves table structures

**Response:**
```json
{
  "project_id": "tenant:project",
  "document_type": "generic",
  "doc_id": "filename.pdf",
  "chunks_added": 123
}
```

**Example cURL:**
```bash
curl -X POST "http://AI-3-IP:9000/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "project_id": "docs_001",
    "user_id": "user@example.com",
    "filename": "document.pdf",
    "mime_type": "application/pdf",
    "text": "Document content here...",
    "document_type": "generic",
    "chunk_strategy": "page_plus_table_aware",
    "chunk_overlap": 200
  }'
```

---

### 🔍 2. Search API

**Endpoint:** `POST /search`

Search for relevant chunks using vector similarity.

**Request:**
```json
{
  "tenant_id": "string",           // Tenant identifier
  "project_id": "string",          // Project identifier
  "user_id": "string",             // User identifier (optional)
  "query": "string",               // Search query (accepts "query" or "question")
  "document_type": "string",       // Filter by document type
  "top_k": 5                       // Number of results (default: 5)
}
```

**Response:**
```json
{
  "chunks": [
    {
      "doc_id": "document.pdf",
      "chunk_id": "document.pdf#c0001",
      "text": "Chunk content...",
      "score": 0.95,
      "metadata": {
        "tenant_id": "acme",
        "project_id": "docs_001",
        "document_type": "generic",
        "raw_text": "Original chunk...",
        "embed_text": "Enriched chunk...",
        "context_enriched": true
      }
    }
  ]
}
```

**Example cURL:**
```bash
curl -X POST "http://AI-3-IP:9000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme",
    "project_id": "docs_001",
    "query": "What is the main topic?",
    "document_type": "generic",
    "top_k": 5
  }'
```

---

### 🏥 3. Health Check

**Endpoint:** `GET /health`

Check if DataFactory is running.

**Response:**
```json
{
  "status": "ok",
  "detail": "ai-3 datafactory up"
}
```

---

### 📊 4. GPU Status (Optional)

**Endpoint:** `GET /gpu/status`

Monitor GPU usage for debugging.

**Response:**
```json
{
  "gpus": [
    {
      "id": 0,
      "name": "NVIDIA GPU",
      "memory_total_mb": 24000,
      "memory_used_mb": 2500,
      "memory_free_mb": 21500,
      "utilization_percent": 15,
      "temperature_c": 45
    }
  ]
}
```

---

## 🔄 Typical RAG Flow (AI-4 → AI-3)

### Step 1: User Uploads Document (AI-4 GUI)
```python
# AI-4 receives file upload from user
file_content = extract_text_from_pdf(uploaded_file)

# Send to AI-3 DataFactory for processing
response = requests.post("http://AI-3-IP:9000/ingest", json={
    "tenant_id": current_tenant,
    "project_id": current_project,
    "user_id": current_user,
    "filename": uploaded_file.name,
    "mime_type": uploaded_file.type,
    "text": file_content,
    "document_type": "generic",  # or detect from content
    "chunk_strategy": "page_plus_table_aware"
})

chunks_added = response.json()["chunks_added"]
# Show user: "✓ Document processed: {chunks_added} chunks indexed"
```

### Step 2: User Asks Question (AI-4 GUI)
```python
# User asks: "What is the main topic of the document?"
query = user_input

# Search AI-3 DataFactory
search_response = requests.post("http://AI-3-IP:9000/search", json={
    "tenant_id": current_tenant,
    "project_id": current_project,
    "query": query,
    "document_type": "generic",
    "top_k": 5
})

chunks = search_response.json()["chunks"]
context = "\n\n".join([chunk["text"] for chunk in chunks])
```

### Step 3: Generate Answer with llama3.1:70b (AI-4)
```python
# ✅ THIS IS YOUR RESPONSIBILITY (AI-4)!
# AI-3 only provided chunks, YOU generate the final answer with 70B

# Use retrieved context to generate answer with 70B model
prompt = f"""Je bent een assistent die vragen beantwoordt op basis van documenten.

Context uit de documenten:
{context}

Vraag: {query}

Geef een gedetailleerd antwoord op basis van de context."""

# ✅ Call Ollama 70B on AI-4 (NOT on AI-3!)
answer = ollama.generate(model="llama3.1:70b", prompt=prompt)

# Show user the answer
display_answer(answer)
```

**KRITIEK:** 
- Deze stap gebeurt op AI-4, NIET op AI-3
- AI-3 heeft GEEN endpoint voor answer generation
- Als je een answer endpoint op AI-3 ziet, is dat alleen voor lokaal testen (fallback)

---

## 🎯 Implementation Checklist

Voor Cline op AI-4:

- [ ] **1. Configure AI-3 API URL**
  ```python
  AI3_DATAFACTORY_URL = "http://AI-3-IP-ADDRESS:9000"
  ```

- [ ] **2. Implement Document Upload Handler**
  - Extract text from file
  - Call `POST /ingest` with file content
  - Show progress/status to user
  - Handle errors gracefully

- [ ] **3. Implement Search Handler**
  - Take user query
  - Call `POST /search` with query
  - Retrieve top-k chunks
  - Build context for LLM

- [ ] **4. Implement Answer Generation**
  - Use retrieved chunks as context
  - Generate answer with llama3.1:70b (on AI-4)
  - Stream response to user
  - Show source chunks (optional)

- [ ] **5. Add Status Monitoring (Optional)**
  - Call `GET /gpu/status` periodically
  - Show AI-3 processing status
  - Display GPU utilization

---

## 🔧 Configuration

### Environment Variables (AI-4)

```bash
# AI-3 DataFactory
export AI3_DATAFACTORY_URL="http://AI-3-IP-ADDRESS:9000"
export AI3_TIMEOUT=600  # 10 min timeout for large documents

# AI-4 LLM
export OLLAMA_MODEL="llama3.1:70b"
export OLLAMA_HOST="http://localhost:11434"
```

### Python Example (AI-4)

```python
import requests
import os

class AI3DataFactory:
    def __init__(self):
        self.base_url = os.getenv("AI3_DATAFACTORY_URL", "http://localhost:9000")
        self.timeout = int(os.getenv("AI3_TIMEOUT", "600"))
    
    def ingest_document(self, tenant_id, project_id, filename, text, 
                       document_type="generic", chunk_strategy="page_plus_table_aware"):
        """Ingest document into AI-3 DataFactory."""
        response = requests.post(
            f"{self.base_url}/ingest",
            json={
                "tenant_id": tenant_id,
                "project_id": project_id,
                "filename": filename,
                "mime_type": "application/pdf",
                "text": text,
                "document_type": document_type,
                "chunk_strategy": chunk_strategy,
                "chunk_overlap": 200
            },
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()
    
    def search(self, tenant_id, project_id, query, document_type="generic", top_k=5):
        """Search for relevant chunks."""
        response = requests.post(
            f"{self.base_url}/search",
            json={
                "tenant_id": tenant_id,
                "project_id": project_id,
                "query": query,
                "document_type": document_type,
                "top_k": top_k
            },
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    
    def health_check(self):
        """Check if DataFactory is running."""
        response = requests.get(f"{self.base_url}/health", timeout=5)
        return response.status_code == 200

# Usage
datafactory = AI3DataFactory()

# Check health
if not datafactory.health_check():
    print("ERROR: AI-3 DataFactory is not responding!")
    
# Ingest document
result = datafactory.ingest_document(
    tenant_id="demo",
    project_id="test_project",
    filename="document.pdf",
    text="Document content...",
    document_type="generic"
)
print(f"✓ Ingested {result['chunks_added']} chunks")

# Search
search_result = datafactory.search(
    tenant_id="demo",
    project_id="test_project",
    query="What is the main topic?",
    top_k=5
)
for chunk in search_result["chunks"]:
    print(f"Score: {chunk['score']:.2f} - {chunk['text'][:100]}...")
```

---

## 📊 DataFactory Capabilities

**What AI-3 DataFactory Provides:**

✅ **OCR Support** - Automatic detection and OCR for scanned PDFs
✅ **Smart Chunking** - 5 different strategies for optimal chunking
✅ **Contextual Enrichment** - LLM-based context enhancement (6x parallel)
✅ **High-Quality Embeddings** - BGE-m3 model (1024-dim)
✅ **Fast Processing** - ~5 MB/min for large documents
✅ **Deduplication** - Automatic chunk deduplication
✅ **Multi-tenant** - Tenant and project isolation
✅ **GPU Optimized** - 8x GPU's (1 for embedding, 6 for enrichment)
✅ **Retrieval Only** - Returns chunks with scores, NOT answers

**What AI-4 Should Provide:**

✅ **User Interface** - Upload, query, display answers
✅ **LLM Generation** - llama3.1:70b for **ALL final answers**
✅ **Context Management** - Build prompts from retrieved chunks
✅ **User Experience** - Progress, errors, source citations
✅ **Business Logic** - Data extraction, workflows, decision making

**BELANGRIJK:** 
- AI-3 geeft alleen chunks terug (raw retrieval)
- AI-4 genereert ALTIJD de final answer met 70B
- Geen uitzonderingen op deze regel in productie

---

## 🚀 Quick Start Command

**For Cline on AI-4:**

```
Integrate with AI-3 RAG DataFactory at http://AI-3-IP:9000

1. Create a DataFactory client class with:
   - ingest_document(tenant_id, project_id, filename, text)
   - search(tenant_id, project_id, query, top_k=5)
   
2. Update document upload flow to:
   - Extract text from uploaded file
   - Call DataFactory ingest API
   - Show user the number of chunks created
   
3. Update query flow to:
   - Call DataFactory search API with user query
   - Retrieve top 5 chunks
   - Use chunks as context for llama3.1:70b
   - Generate and show answer to user
   
4. Add health check on startup to verify AI-3 connection

The DataFactory handles:
- OCR (automatic for scanned PDFs)
- Chunking (smart strategies)
- Enrichment (6x parallel LLM)
- Embedding (BGE-m3)
- Vector search (FAISS)

You only need to call the simple APIs!
```

---

## 🤖 Automatic Processing Features

### OCR Auto-Detection
**De DataFactory analyseert automatisch of OCR nodig is:**
- ✅ Bij file upload (`/v1/rag/ingest/file`) wordt automatisch OCR toegepast als nodig
- ✅ Smart detection: Als pages < 100 chars hebben → OCR wordt toegepast
- ✅ Hybrid approach: Native extractie + OCR combined voor beste resultaat
- ✅ Transparant: Je hoeft niets te doen, het gebeurt automatisch

**Ondersteuning:**
- PDF's: Auto OCR voor scanned documents
- Images: Tesseract OCR (Nederlands + Engels)
- Hybrid: Best of native + OCR extractie

### Chunking Strategy Auto-Detection
**De DataFactory kiest automatisch de beste chunking strategie:**
- ✅ Analyseert content type (PDF, chat, markdown, etc.)
- ✅ Detecteert structuren (pages, tables, conversations)
- ✅ Kiest optimale strategie met confidence scores
- ✅ 5 strategieën beschikbaar (zie Chunking Strategies sectie hieronder)

**Je kunt ook expliciet een strategie opgeven** via `chunk_strategy` parameter.

---

## 🔧 Chunking Strategies (Nieuw!)

De DataFactory ondersteunt nu **5 chunking strategieën**:

| Strategie | Gebruik Voor | Auto-Detect |
|-----------|--------------|-------------|
| `default` | Normale tekst, artikelen | ✓ |
| `page_plus_table_aware` | PDF's, rapporten | ✓ (0.95) |
| `semantic_sections` | Markdown, docs met headers | ✓ (0.85) |
| `conversation_turns` | WhatsApp, chats, Q&A | ✓ (0.90) |
| `table_aware` | Data met tabellen | ✓ (0.85) |

**Gebruik:**
```json
{
  "chunk_strategy": "page_plus_table_aware",  // Optioneel
  "chunk_overlap": 200                        // Optioneel (chars)
}
```

**Nieuwe Endpoints:**
- `GET /strategies/list` - Lijst alle beschikbare strategieën
- `POST /strategies/detect` - Auto-detect beste strategie voor tekst
- `POST /strategies/test` - Test strategie met sample data

---

## 📝 Notes

- **Timeout:** Large documents (45MB+) can take 5-10 minutes to process. Set appropriate timeouts.
- **Error Handling:** DataFactory may be busy processing other documents. Implement retry logic.
- **Webhooks:** DataFactory sends status updates to registered webhook URLs (if configured).
- **Monitoring:** Use `/gpu/status` endpoint to monitor AI-3 server load.
- **OCR:** Happens automatically for scanned PDFs - no action needed from AI-4
- **Chunking:** Auto-selected based on content - can be overridden via `chunk_strategy`

---

## ✅ Success Criteria

You'll know it works when:
1. User uploads PDF → AI-3 processes → Shows "X chunks indexed"
2. User asks question → AI-3 searches → Returns relevant chunks
3. AI-4 generates answer using chunks → User sees accurate response
4. Large PDFs (45MB+) process successfully in ~5-10 minutes
5. OCR automatically triggers for scanned documents

---

---

## 🤖 Prompt Voor Cline Op AI-4

**Kopieer deze prompt naar Cline op AI-4:**

```
Integreer met de AI-3 RAG DataFactory voor document processing en vector search.

CONFIGURATIE:
- DataFactory URL: http://AI-3-IP-ADDRESS:9000
- Timeout: 10 minuten (voor grote documenten)

ENDPOINTS (ongewijzigd, backwards compatible):
1. POST /ingest - Upload en process document
   - Automatic OCR voor scanned PDFs
   - Automatic chunking strategie selectie
   - Returns: chunks_added count

2. POST /search - Zoek relevante chunks
   - Vector similarity search
   - Returns: top_k chunks met scores

3. GET /health - Health check

NIEUWE FEATURES (optioneel te gebruiken):
4. GET /strategies/list - Lijst chunking strategieën
5. POST /strategies/detect - Auto-detect beste strategie
6. POST /strategies/test - Test strategie vooraf

BELANGRIJKE DETAILS:
- OCR gebeurt AUTOMATISCH bij /ingest (geen actie nodig)
- Chunking strategie wordt AUTOMATISCH gekozen (of override via chunk_strategy)
- Processing duurt 30s voor kleine docs, 5-10 min voor grote docs (45MB+)
- DataFactory draait 6 GPU's parallel voor enrichment
- Embeddings zijn contextually enriched (LLM-enhanced)

🚨 KRITIEKE ARCHITECTUUR REGEL:
- AI-3 DataFactory = RETRIEVAL ONLY (chunks teruggeven)
- AI-4 = ANSWER GENERATION (70B model voor final answers)
- AI-3 mag GEEN final answers genereren (behalve lokale test fallback)
- Alle gebruikersvragen → AI-4 → search AI-3 → answer met 70B → user

IMPLEMENTATIE:
1. Maak DataFactory client class:
   - ingest_document(tenant_id, project_id, filename, text, **kwargs)
   - search(tenant_id, project_id, query, top_k=5)
   - health_check()

2. Update document upload flow:
   - Extract text from file (pypdf, docx, etc.)
   - Call DataFactory /ingest endpoint
   - Show user: "X chunks indexed"
   - Handle 10 min timeout voor grote files

3. Update query flow:
   - Call DataFactory /search endpoint
   - Get top_k chunks
   - Use as context for llama3.1:70b
   - Generate answer
   - Show to user

4. Error handling:
   - Timeout → retry met progress indicator
   - 404 → index not found, re-ingest
   - 500 → DataFactory issue, show error

OPTIONELE FEATURES:
- Chunking strategie selectie UI
- OCR status monitoring
- GPU status display
- Strategy testing tool

De DataFactory is production-ready en getest met docs tot 45MB.
Alle processing (OCR, chunking, enrichment, embedding) gebeurt automatisch.
Jij hoeft alleen /ingest en /search aan te roepen!

Implementeer dit nu als Python client class met error handling.
```

---

**Good luck with the integration! 🚀**

*The AI-3 DataFactory is production-ready and thoroughly tested with documents from 1MB to 45MB.*
