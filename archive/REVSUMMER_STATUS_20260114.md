# Review Summarizer Integration Status - 14 januari 2026

## ✅ GEREED OP AI-3

### 1. Menu Document Type Detection
- ✅ `classify_document_type()` herkent nu `menu_*.txt` → `type=menu`
- ✅ Fallback content detection: prijzen + menu keywords
- ✅ Test: `menu_20.txt` → correct gedetecteerd als `type=menu`

### 2. Menu Chunking Strategy
- ✅ Strategy skip section headers (`=== Voorgerechten ===`)
- ✅ Atomic chunking: 1 gerecht = 1 chunk
- ✅ Unicode € symbol support
- ✅ Test: 2 gerechten → 2 chunks (was: 1 chunk)

### 3. API Endpoints
- ✅ `/ingest` - Works voor ZOWEL reviews ALS menus
- ✅ `/search` - Hybrid search met BM25 + vector
- ✅ Auto-detection van strategies via filename
- ✅ Enrichment met 8B models (parallel op GPU 2-7)

### 4. Services Running
```
✅ DataFactory:  http://10.0.1.227:9000 (PID 1388894)
✅ Ollama 8B:    5x instances (GPU 2-7)
✅ Embedding:    GPU 0 dedicated
✅ Health:       {"status":"ok"}
```

---

## ❌ PROBLEMEN IN RS (AI-4)

### Probleem 1: RS doet local embeddings (CUDA OOM)
**Symptoom:**
```
CUDA out of memory. Tried to allocate 48.00 MiB. 
GPU 0 has 6.71 GiB in use (70B model!)
```

**Oorzaak:**
- RS probeert zelf embeddings te maken op AI-4
- Conflict met 70B model op GPU 0
- Fallback naar local processing wanneer AI-3 unreachable

**Fix:**
```python
# ❌ VERWIJDER local embedding code in RS:
model = SentenceTransformer('BAAI/bge-m3', device='cuda')
embeddings = model.encode(reviews)

# ✅ GEBRUIK alleen HTTP calls naar AI-3:
response = requests.post(
    "http://10.0.1.227:9000/ingest",
    json={
        "tenant_id": "revsummer",
        "project_id": str(restaurant_id),
        "filename": f"reviews_{restaurant_id}.txt",
        "text": reviews_text,
        "metadata": {"restaurant_name": name}
    },
    timeout=60  # Lang genoeg voor enrichment!
)
```

### Probleem 2: Menu ingest wordt niet verstuurd
**Symptoom:**
```
[10:52:52] ⚠️ AI-3 menu ingest failed: DataFactory returned None
```

**Analyse:**
- AI-3 logs tonen GEEN menu ingests (alleen reviews)
- curl test naar AI-3 WERKT wel
- RS stuurt blijkbaar geen menu POST request

**Mogelijke oorzaken:**
1. `restaurant.menu_items` is leeg
2. Menu POST code zit achter `if` die False evalueert
3. Feature flag check die niet klopt
4. Exception wordt geslikt

**Debug stappen:**
```python
print(f"[DEBUG] Restaurant {id}: has_menu={bool(menu_items)}")
print(f"[DEBUG] Menu items count: {len(menu_items)}")

if menu_items:
    menu_text = format_menu(menu_items)
    print(f"[DEBUG] Menu text: {len(menu_text)} chars")
    print(f"[DEBUG] Posting to: {AI3_URL}/ingest")
    
    response = requests.post(...)
    print(f"[DEBUG] Response: {response.status_code}")
    print(f"[DEBUG] Body: {response.json()}")
```

### Probleem 3: Timeout/connectivity
**Check:**
1. Welk IP gebruikt RS? `10.0.1.227` of `10.0.1.44`?
2. Timeout lang genoeg? (minimum 60 sec voor enrichment)
3. Fallback disabled? (moet NIET fallback naar local)

---

## 📋 ACTIE VOOR RS TEAM

### Prioriteit 1: Verwijder local embeddings
```python
# In RS code, zoek en verwijder:
- from sentence_transformers import SentenceTransformer
- model = SentenceTransformer(...)
- embeddings = model.encode(...)
- torch.cuda.*
- Multi-GPU spawn code
```

### Prioriteit 2: Fix HTTP client
```python
AI3_URL = "http://10.0.1.227:9000"  # AI-3 intern IP

def ingest_to_ai3(data_type, restaurant_id, text):
    payload = {
        "tenant_id": "revsummer",
        "project_id": str(restaurant_id),
        "filename": f"{data_type}_{restaurant_id}.txt",
        "text": text,
        "metadata": {"restaurant_name": restaurant.name}
    }
    
    try:
        response = requests.post(
            f"{AI3_URL}/ingest",
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        print(f"✓ {data_type}: {result['chunks_added']} chunks")
        return result
    except Exception as e:
        print(f"❌ {data_type} failed: {e}")
        raise  # Don't fallback!
```

### Prioriteit 3: Ingest reviews + menus
```python
# Voor elk restaurant:

# 1. Reviews
reviews_text = "\n\n".join([
    f"Review door {r.author}:\nRating: {r.rating}/5\n{r.text}"
    for r in restaurant.reviews
])
ingest_to_ai3("reviews", restaurant.id, reviews_text)

# 2. Menu (als beschikbaar)
if restaurant.menu_items:
    menu_text = "\n\n".join([
        f"{item.name}\n{item.description}\n€ {item.price}"
        for item in restaurant.menu_items
    ])
    ingest_to_ai3("menu", restaurant.id, menu_text)

# 3. Search
results = requests.post(
    f"{AI3_URL}/search",
    json={
        "tenant_id": "revsummer",
        "project_id": str(restaurant.id),
        "query": "Wat vinden klanten van de service?",
        "document_type": "google_reviews",  # Voor reviews
        "top_k": 10
    }
).json()
```

---

## 🎯 ARCHITECTUUR (TER HERINNERING)

```
AI-4 (RS):
├─ GPU 0: 70B model (blijft resident!)
├─ Taken: Orchestration, 70B analysis
└─ GEEN PyTorch/CUDA operaties!

AI-3 (DataFactory):
├─ GPU 0: Embedding model (dedicated)
├─ GPU 2-7: 8B enrichment (parallel)
├─ Taken: Chunking, enrichment, embedding, vector storage
└─ Endpoints: /ingest, /search
```

**RS moet ALLEEN HTTP calls maken naar AI-3!**

---

## 📁 AANGEPASTE FILES (14-01-2026)

1. **app.py**
   - Line 115: Added `import re`
   - Line 118-145: Enhanced `classify_document_type()` met menu detection

2. **chunking_strategies/strategies/menus.py**
   - Line 251-276: Fixed `_extract_menu_items()` pattern 2
   - Skip section headers (=== Header ===)
   - Flexible price regex (Unicode € support)

3. **REVSUMMER_INTEGRATION_PROMPT.md**
   - Added warning: "Menu ingest IS beschikbaar"
   - Clarified: SAME endpoint for reviews and menus

4. **REVSUMMER_PIPELINE_EVALUATION.md**
   - Complete E2E test results
   - Strategy detection analysis
   - Performance metrics

5. **Nieuwe file: REVSUMMER_STATUS_20260114.md**
   - Dit document

---

## 🧪 TEST COMMANDO'S

```bash
# Test AI-3 health
curl http://10.0.1.227:9000/health

# Test reviews ingest
curl -X POST http://10.0.1.227:9000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "revsummer",
    "project_id": "test_123",
    "filename": "reviews_test_123.txt",
    "text": "Review door Jan:\nRating: 5/5\nGeweldig!",
    "metadata": {"restaurant_name": "Test"}
  }'

# Test menu ingest
curl -X POST http://10.0.1.227:9000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "revsummer",
    "project_id": "test_123",
    "filename": "menu_test_123.txt",
    "text": "Pasta carbonara\nRomige pasta\n€ 12.50",
    "metadata": {"restaurant_name": "Test"}
  }'

# Run complete test
python test_revsummer_pipeline.py
```

---

## 📞 CONTACT

Voor vragen over AI-3 DataFactory:
- Logs: `/home/daniel/Projects/RAG-ai3-chunk-embed/logs/`
- Code: GitHub repo
- Server: `ssh daniel@10.0.1.227`

**AI-3 is production ready. RS HTTP client moet gefixed worden.**
