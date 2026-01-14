# Service Startup Fix - Robuuste Service Management

## Probleem Analyse

### Wat ging er mis?

**Root Cause:**
De startup script gebruikte verkeerde commando's voor FastAPI services:

```bash
# FOUT - werkt niet voor FastAPI apps:
python doc_analyzer_service.py --port 9100
python reranker_service.py --port 9200

# CORRECT - FastAPI apps moeten met uvicorn draaien:
uvicorn doc_analyzer_service:app --host 0.0.0.0 --port 9100
uvicorn reranker_service:app --host 0.0.0.0 --port 9200
```

**Waarom faalde dit?**
- FastAPI applicaties zijn ASGI apps, geen standalone scripts
- Ze hebben een ASGI server (uvicorn) nodig om te draaien
- `python service.py` start geen HTTP server - de app bleef hangen
- Geen error messages → lege logs → moeilijk debuggen

### Service Types in deze Stack:

1. **FastAPI Services** (need uvicorn):
   - `app.py` (DataFactory)
   - `doc_analyzer_service.py` (Doc Analyzer)
   - `reranker_service.py` (Reranker)

2. **Standalone Python Script**:
   - `ocr_service.py` (heeft eigen Flask server)

3. **External Binary**:
   - Ollama (system service)

## Oplossing: Robuust Startup Script

### 1. Correcte Service Start Commands

```bash
# DataFactory - FastAPI met uvicorn
uvicorn app:app \
  --host 0.0.0.0 \
  --port 9000 \
  --timeout-keep-alive 7200 \
  > logs/datafactory_9000.log 2>&1 &

# Doc Analyzer - FastAPI met uvicorn  
uvicorn doc_analyzer_service:app \
  --host 0.0.0.0 \
  --port 9100 \
  --timeout-keep-alive 3600 \
  > logs/doc_analyzer_9100.log 2>&1 &

# Reranker - FastAPI met uvicorn
CUDA_VISIBLE_DEVICES=1 \
uvicorn reranker_service:app \
  --host 0.0.0.0 \
  --port 9200 \
  --timeout-keep-alive 3600 \
  > logs/reranker_9200.log 2>&1 &

# OCR - Standalone script met eigen Flask server
CUDA_VISIBLE_DEVICES=2 \
python ocr_service.py --port 9300 \
  > logs/ocr_9300.log 2>&1 &
```

### 2. Robuuste Health Checks met Error Detection

**Oud (zwak):**
```bash
# Checkt alleen, rapporteert niet als het faalt
for i in {1..10}; do
    if curl -s http://localhost:9100/health > /dev/null 2>&1; then
        echo "OK"
        break
    fi
    sleep 1
done
```

**Nieuw (robuust):**
```bash
HEALTH_CHECK_FAILED=0

echo -n "[CHECK] Doc Analyzer (port 9100)... "
READY=0
for i in {1..15}; do
    if curl -s http://localhost:9100/health > /dev/null 2>&1; then
        echo "OK"
        READY=1
        break
    fi
    sleep 1
done

if [ $READY -eq 0 ]; then
    echo "FAILED - check logs/doc_analyzer_9100.log"
    HEALTH_CHECK_FAILED=1
fi

# Na alle checks: exit als iets fout ging
if [ $HEALTH_CHECK_FAILED -eq 1 ]; then
    echo "[ERROR] Some services failed to start!"
    echo "Check the logs in $PROJECT_DIR/logs/"
    exit 1
fi
```

**Voordelen:**
- ✅ Script stopt bij fouten (`exit 1`)
- ✅ Duidelijke foutmelding met logfile locatie
- ✅ Geen half-werkende deployments
- ✅ Makkelijk te debuggen

### 3. Service-Specific Timeouts

Verschillende services hebben verschillende startup tijden:

```bash
# Doc Analyzer (CPU) - 15 seconden
for i in {1..15}; do

# Reranker (GPU 1 load) - 20 seconden  
for i in {1..20}; do

# OCR Service (GPU 2 + EasyOCR) - 25 seconden
for i in {1..25}; do

# DataFactory (GPU 0 + BGE-M3) - 30 seconden
for i in {1..30}; do
```

Dit voorkomt false negatives tijdens startup.

## Best Practices voor Service Management

### 1. Logging Strategy

**Standaard:**
```bash
service_command > logs/service_name.log 2>&1 &
```

**Betekenis:**
- `> logs/service_name.log` → stdout naar file
- `2>&1` → stderr ook naar file
- `&` → run in background

### 2. Process Cleanup

**Voor elke service:**
```bash
# Cleanup old processes
pkill -f "uvicorn app:app" || true
pkill -f "reranker_service" || true
pkill -f "doc_analyzer_service" || true
```

**Waarom `|| true`?**
- `pkill` geeft exit code 1 als geen proces gevonden
- `|| true` voorkomt dat script stopt (we hebben `set -e`)
- Cleanup mag falen, maar niet de hele startup blokkeren

### 3. GPU Pinning

**Expliciet GPU's toewijzen:**
```bash
CUDA_VISIBLE_DEVICES=0 uvicorn app:app ...        # DataFactory op GPU 0
CUDA_VISIBLE_DEVICES=1 uvicorn reranker_service:app ...  # Reranker op GPU 1
CUDA_VISIBLE_DEVICES=2 python ocr_service.py ...  # OCR op GPU 2
```

**Voordelen:**
- Geen GPU resource conflicts
- Voorspelbare performance
- Makkelijk te monitoren met `nvidia-smi`

### 4. Environment Variables

**Voor DataFactory:**
```bash
AUTO_UNLOAD_EMBEDDER=false         # Keep model in memory
DISABLE_STARTUP_EMBED_WARMUP=false # Warmup tijdens startup
DISABLE_STARTUP_CORPUS_LOAD=true   # Skip corpus (sneller startup)
HYBRID_SEARCH_ENABLED=true         # Enable hybrid search
RERANK_ENABLED=true                # Enable reranking
CONTEXT_ENABLED=true               # Enable contextual enrichment
OLLAMA_MULTI_GPU=true              # Use multiple Ollama instances
OLLAMA_BASE_PORT=11435             # First Ollama port
OLLAMA_NUM_INSTANCES=4             # 4 parallel instances
CONTEXT_MAX_WORKERS=4              # 4 parallel workers
```

Dit configureert services zonder code changes.

## Deployment Checklist

Voordat je `start_AI3_services.sh` draait:

- [ ] Virtuele environment geactiveerd: `source .venv/bin/activate`
- [ ] Ollama models gedownload: `ollama pull llama3.1:8b`
- [ ] GPU's beschikbaar: `nvidia-smi`
- [ ] Oude processen gestopt: script doet dit automatisch
- [ ] Logs directory bestaat: `mkdir -p logs`
- [ ] Poorten vrij: `ss -tlnp | grep -E ":(9000|9100|9200|9300)"`

## Monitoring en Troubleshooting

### Check Service Status

```bash
# Alle services
curl http://localhost:9000/health  # DataFactory
curl http://localhost:9100/health  # Doc Analyzer
curl http://localhost:9200/health  # Reranker
curl http://localhost:9300/health  # OCR Service

# Ollama instances
curl http://localhost:11435/api/tags
curl http://localhost:11436/api/tags
curl http://localhost:11437/api/tags
curl http://localhost:11438/api/tags
```

### Check Running Processes

```bash
ps aux | grep -E "(uvicorn|ocr_service|ollama)" | grep -v grep
```

### Check Logs

```bash
# Real-time monitoring
tail -f logs/datafactory_9000.log
tail -f logs/doc_analyzer_9100.log
tail -f logs/reranker_9200.log
tail -f logs/ocr_9300.log

# Last 50 lines
tail -50 logs/datafactory_9000.log
```

### Common Issues

**Service niet bereikbaar:**
```bash
# Check of service draait
ps aux | grep uvicorn

# Check of poort open is
ss -tlnp | grep 9000

# Check logs voor errors
tail -100 logs/datafactory_9000.log
```

**GPU out of memory:**
```bash
# Check GPU usage
nvidia-smi

# Cleanup GPU's
pkill -f ollama
pkill -f uvicorn
sleep 5
# Restart services
```

**Models not loading:**
```bash
# Check Ollama models
ollama list

# Pull missing models
ollama pull llama3.1:8b
```

## Toekomstige Verbeteringen

### 1. Systemd Services (Productie)

Voor productie: maak systemd service files:

```ini
# /etc/systemd/system/ai3-datafactory.service
[Unit]
Description=AI-3 DataFactory Service
After=network.target

[Service]
Type=simple
User=daniel
WorkingDirectory=/home/daniel/Projects/RAG-ai3-chunk-embed
Environment="CUDA_VISIBLE_DEVICES=0"
Environment="PATH=/home/daniel/Projects/RAG-ai3-chunk-embed/.venv/bin:/usr/bin"
ExecStart=/home/daniel/Projects/RAG-ai3-chunk-embed/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 9000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Voordelen:**
- Automatic restart on failure
- Boot-time startup
- Standard logging via journalctl
- Dependency management

### 2. Docker Compose (Alternative)

```yaml
version: '3.8'
services:
  datafactory:
    build: .
    ports:
      - "9000:9000"
    environment:
      CUDA_VISIBLE_DEVICES: "0"
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
```

### 3. Health Check Endpoint voor Load Balancer

Uitbreiden health endpoints met detailed status:

```python
@app.get("/health/detailed")
async def health_detailed():
    return {
        "status": "ok",
        "service": "datafactory",
        "gpu": {
            "device": 0,
            "memory_used_mb": ...,
            "temperature_c": ...,
        },
        "models": {
            "embedder": "loaded",
            "ollama_instances": 4,
        },
        "uptime_seconds": ...,
    }
```

## Conclusie

**Wat we gefixed hebben:**
✅ Correcte service start commando's (uvicorn voor FastAPI)
✅ Robuuste health checks met error handling
✅ Script stopt bij failures (geen half-werkende deployments)
✅ Service-specific timeouts voor accurate health checks
✅ Duidelijke error messages met log locations

**Resultaat:**
De startup script start nu **altijd** alle services correct of faalt expliciet met duidelijke error messages. Geen stille failures meer.
