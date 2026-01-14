#!/bin/bash
#
# AI-3 Services Optimized Startup
# ================================
# 
# GPU Allocation Strategy:
#   GPU 0: DataFactory Embedding (BGE-M3) - Always resident
#   GPU 1: Reranker (BGE-reranker-v2-m3) - Always resident
#   GPU 2: OCR Service (EasyOCR) - GPU-accelerated text extraction
#   GPU 3: Doc Analyzer (HuggingFace) - RESERVED for future GPU enhancement
#   GPU 4-7: 4x Ollama llama3.1:8b for parallel enrichment
#
# Benefits:
#   - 4x faster enrichment (~35s vs 140s per document)
#   - Clean GPU pinning (no cleanup needed)
#   - 2 GPUs reserved for future expansion
#   - Predictable, stable performance
#

set -e

PROJECT_DIR="/home/daniel/Projects/RAG-ai3-chunk-embed"
cd "$PROJECT_DIR"

# Activate venv
source .venv/bin/activate

# Ollama config
export OLLAMA_MODELS=/usr/share/ollama/.ollama/models

echo "========================================"
echo "AI-3 Services - Optimized Startup"
echo "========================================"
echo "Project: $PROJECT_DIR"
echo "GPU Strategy: 0=Embed, 1=Rerank, 2-3=Reserved, 4-7=Enrichment"
echo ""

# ===========================================
# STEP 1: Cleanup old processes
# ===========================================
echo "=== STEP 1: Cleanup ==="
pkill -f "uvicorn app:app" || true
pkill -f "reranker_service" || true
pkill -f "doc_analyzer_service" || true
pkill -f "ollama serve" || true
pkill -f "ollama runner" || true
sleep 2
echo "[OK] Old processes cleaned"
echo ""

# ===========================================
# STEP 2: Start Ollama main daemon
# ===========================================
echo "=== STEP 2: Start Ollama Daemon ==="
if pgrep -f "ollama serve" > /dev/null; then
    echo "[OK] Ollama already running"
else
    OLLAMA_MODELS=$OLLAMA_MODELS ollama serve > logs/ollama_main.log 2>&1 &
    sleep 3
    echo "[OK] Ollama daemon started"
fi
echo ""

# ===========================================
# STEP 3: Start 4x Ollama instances (GPU 4-7)
# ===========================================
echo "=== STEP 3: Start 4x Ollama Instances (GPU 4-7) ==="

# Instance 1 - GPU 4 - Port 11435
echo "[START] Ollama Instance 1 (GPU 4, port 11435)..."
CUDA_VISIBLE_DEVICES=4 \
OLLAMA_HOST=0.0.0.0:11435 \
OLLAMA_MODELS=$OLLAMA_MODELS \
ollama serve > logs/ollama_gpu4_11435.log 2>&1 &
OLLAMA_PID_1=$!

# Instance 2 - GPU 5 - Port 11436
echo "[START] Ollama Instance 2 (GPU 5, port 11436)..."
CUDA_VISIBLE_DEVICES=5 \
OLLAMA_HOST=0.0.0.0:11436 \
OLLAMA_MODELS=$OLLAMA_MODELS \
ollama serve > logs/ollama_gpu5_11436.log 2>&1 &
OLLAMA_PID_2=$!

# Instance 3 - GPU 6 - Port 11437
echo "[START] Ollama Instance 3 (GPU 6, port 11437)..."
CUDA_VISIBLE_DEVICES=6 \
OLLAMA_HOST=0.0.0.0:11437 \
OLLAMA_MODELS=$OLLAMA_MODELS \
ollama serve > logs/ollama_gpu6_11437.log 2>&1 &
OLLAMA_PID_3=$!

# Instance 4 - GPU 7 - Port 11438
echo "[START] Ollama Instance 4 (GPU 7, port 11438)..."
CUDA_VISIBLE_DEVICES=7 \
OLLAMA_HOST=0.0.0.0:11438 \
OLLAMA_MODELS=$OLLAMA_MODELS \
ollama serve > logs/ollama_gpu7_11438.log 2>&1 &
OLLAMA_PID_4=$!

echo "[WAIT] Waiting for Ollama instances to start..."
sleep 5

# Verify instances are running
for port in 11435 11436 11437 11438; do
    if curl -s http://localhost:$port/api/tags > /dev/null 2>&1; then
        echo "[OK] Ollama instance on port $port is UP"
    else
        echo "[WARN] Ollama instance on port $port not responding"
    fi
done
echo ""

# ===========================================
# STEP 4: Pre-load models on all Ollama instances (async)
# ===========================================
echo "=== STEP 4: Pre-load llama3.1:8b on all 4 instances (async) ==="
for port in 11435 11436 11437 11438; do
    echo "[LOAD] Triggering model load on port $port (background)..."
    (curl -s --max-time 120 http://localhost:$port/api/generate -d '{
        "model": "llama3.1:8b",
        "prompt": "warmup",
        "stream": false,
        "keep_alive": "30m"
    }' > /dev/null 2>&1 || echo "[WARN] Model load on port $port timed out (will load on first use)" ) &
done

echo "[INFO] Models loading in background (will be ready on first use)"
echo "[INFO] Continuing with service startup..."
echo ""

# ===========================================
# STEP 5: Start DataFactory (GPU 0)
# ===========================================
echo "=== STEP 5: Start DataFactory (GPU 0 - Embedding) ==="
CUDA_VISIBLE_DEVICES=0 \
AUTO_UNLOAD_EMBEDDER=false \
DISABLE_STARTUP_EMBED_WARMUP=false \
DISABLE_STARTUP_CORPUS_LOAD=true \
HYBRID_SEARCH_ENABLED=true \
RERANK_ENABLED=true \
CONTEXT_ENABLED=true \
OLLAMA_MULTI_GPU=true \
OLLAMA_BASE_PORT=11435 \
OLLAMA_NUM_INSTANCES=4 \
CONTEXT_MAX_WORKERS=4 \
uvicorn app:app \
  --host 0.0.0.0 \
  --port 9000 \
  --timeout-keep-alive 7200 \
  --timeout-graceful-shutdown 30 \
  --limit-concurrency 1000 \
  --backlog 2048 \
  > logs/datafactory_9000.log 2>&1 &
DATAFACTORY_PID=$!
echo "[START] DataFactory PID: $DATAFACTORY_PID"
echo ""

# ===========================================
# STEP 6: Start Doc Analyzer (CPU) - FastAPI with uvicorn
# ===========================================
echo "=== STEP 6: Start Doc Analyzer (CPU) ==="
uvicorn doc_analyzer_service:app \
  --host 0.0.0.0 \
  --port 9100 \
  --timeout-keep-alive 3600 \
  > logs/doc_analyzer_9100.log 2>&1 &
DOC_ANALYZER_PID=$!
echo "[START] Doc Analyzer PID: $DOC_ANALYZER_PID"
echo ""

# ===========================================
# STEP 7: Start Reranker (GPU 1) - FastAPI with uvicorn
# ===========================================
echo "=== STEP 7: Start Reranker (GPU 1) ==="
CUDA_VISIBLE_DEVICES=1 \
uvicorn reranker_service:app \
  --host 0.0.0.0 \
  --port 9200 \
  --timeout-keep-alive 3600 \
  > logs/reranker_9200.log 2>&1 &
RERANKER_PID=$!
echo "[START] Reranker PID: $RERANKER_PID"
echo ""

# ===========================================
# STEP 8: Start OCR Service (GPU 2) - Direct Python script
# ===========================================
echo "=== STEP 8: Start OCR Service (GPU 2) ==="
CUDA_VISIBLE_DEVICES=2 \
python ocr_service.py --port 9300 \
  > logs/ocr_9300.log 2>&1 &
OCR_PID=$!
echo "[START] OCR Service PID: $OCR_PID"
echo ""

# ===========================================
# STEP 9: Health checks with proper error handling
# ===========================================
echo "=== STEP 9: Health Checks ==="

HEALTH_CHECK_FAILED=0

# DataFactory - critical service
echo -n "[CHECK] DataFactory (port 9000)... "
READY=0
for i in {1..30}; do
    if curl -s http://localhost:9000/health > /dev/null 2>&1; then
        echo "OK"
        READY=1
        break
    fi
    sleep 1
done
if [ $READY -eq 0 ]; then
    echo "FAILED - check logs/datafactory_9000.log"
    HEALTH_CHECK_FAILED=1
fi

# Doc Analyzer - critical for pipeline
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

# Reranker - required for hybrid search
echo -n "[CHECK] Reranker (port 9200)... "
READY=0
for i in {1..20}; do
    if curl -s http://localhost:9200/health > /dev/null 2>&1; then
        echo "OK"
        READY=1
        break
    fi
    sleep 1
done
if [ $READY -eq 0 ]; then
    echo "FAILED - check logs/reranker_9200.log"
    HEALTH_CHECK_FAILED=1
fi

# OCR Service - required for scanned docs
echo -n "[CHECK] OCR Service (port 9300)... "
READY=0
for i in {1..25}; do
    if curl -s http://localhost:9300/health > /dev/null 2>&1; then
        echo "OK"
        READY=1
        break
    fi
    sleep 1
done
if [ $READY -eq 0 ]; then
    echo "FAILED - check logs/ocr_9300.log"
    HEALTH_CHECK_FAILED=1
fi

echo ""

# Check if any health checks failed
if [ $HEALTH_CHECK_FAILED -eq 1 ]; then
    echo "========================================" 
    echo "[ERROR] Some services failed to start!"
    echo "========================================" 
    echo ""
    echo "Check the logs in $PROJECT_DIR/logs/"
    echo ""
    exit 1
fi

# ===========================================
# STEP 10: GPU Status
# ===========================================
echo "=== STEP 10: GPU Status ==="
nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.free,temperature.gpu \
  --format=csv,noheader,nounits | \
  awk -F', ' '{printf "  GPU %s: %3s%% util, %5s MB used, %5s MB free, %2s°C\n", $1, $3, $4, $5, $6}'
echo ""

# ===========================================
# DONE
# ===========================================
echo "========================================"
echo "[OK] All Services Started!"
echo "========================================"
echo ""
echo "Endpoints:"
echo "  http://localhost:9000  (DataFactory - GPU 0)"
echo "  http://localhost:9100  (Doc Analyzer - CPU)"
echo "  http://localhost:9200  (Reranker - GPU 1)"
echo "  http://localhost:9300  (OCR Service - GPU 2)"
echo "  http://localhost:11435 (Ollama GPU 4)"
echo "  http://localhost:11436 (Ollama GPU 5)"
echo "  http://localhost:11437 (Ollama GPU 6)"
echo "  http://localhost:11438 (Ollama GPU 7)"
echo ""
echo "External access (from AI-4):"
echo "  http://10.0.1.44:9000  (DataFactory)"
echo "  http://10.0.1.44:9100  (Doc Analyzer)"
echo "  http://10.0.1.44:9200  (Reranker)"
echo "  http://10.0.1.44:9300  (OCR Service)"
echo ""
echo "GPU Allocation:"
echo "  GPU 0: DataFactory Embedding (always resident)"
echo "  GPU 1: Reranker (always resident)"
echo "  GPU 2: OCR Service (EasyOCR - scanned document extraction)"
echo "  GPU 3: RESERVED (for future Doc Analyzer GPU enhancement)"
echo "  GPU 4-7: 4x Ollama for parallel enrichment"
echo ""
echo "Expected Performance:"
echo "  Enrichment: ~35 sec/document (4x faster than before!)"
echo "  Throughput: ~1.7 documents/minute"
echo ""
echo "Logs: $PROJECT_DIR/logs/"
echo "========================================"
