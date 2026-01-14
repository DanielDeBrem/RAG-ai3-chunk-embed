#!/bin/bash
# ============================================
# AI-3 Complete Startup Script
# Starts all AI-3 services met GPU pinning
# ============================================

set -e

echo "=========================================="
echo "AI-3 Ingestion Factory Startup"
echo "=========================================="

# Kleuren voor output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuratie
export AI4_LLM70_BASE_URL="${AI4_LLM70_BASE_URL:-http://10.0.1.227:8000}"
export AI4_LLM70_ENABLED="${AI4_LLM70_ENABLED:-true}"
export AI4_FALLBACK_TO_HEURISTICS="${AI4_FALLBACK_TO_HEURISTICS:-true}"

export AI3_EMBED_GPU="${AI3_EMBED_GPU:-0}"
export AI3_RERANK_GPU="${AI3_RERANK_GPU:-1}"
export AI3_WORKER_GPUS="${AI3_WORKER_GPUS:-2,3,4,5,6,7}"

export DATAFACTORY_PORT="${DATAFACTORY_PORT:-9000}"
export DOC_ANALYZER_PORT="${DOC_ANALYZER_PORT:-9100}"
export RERANKER_PORT="${RERANKER_PORT:-9200}"

# Feature flags (70B-first stability)
export AUTO_UNLOAD_EMBEDDER="${AUTO_UNLOAD_EMBEDDER:-true}"
export AUTO_UNLOAD_RERANKER="${AUTO_UNLOAD_RERANKER:-true}"
export DISABLE_STARTUP_EMBED_WARMUP="${DISABLE_STARTUP_EMBED_WARMUP:-true}"
export DISABLE_STARTUP_CORPUS_LOAD="${DISABLE_STARTUP_CORPUS_LOAD:-true}"

# Models
export EMBED_MODEL_NAME="${EMBED_MODEL_NAME:-BAAI/bge-m3}"
export RERANK_MODEL="${RERANK_MODEL:-BAAI/bge-reranker-v2-m3}"

# Log directory
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

echo ""
echo "Configuration:"
echo "  AI4_LLM70_BASE_URL: $AI4_LLM70_BASE_URL"
echo "  AI4_LLM70_ENABLED: $AI4_LLM70_ENABLED"
echo "  AI3_EMBED_GPU: $AI3_EMBED_GPU"
echo "  AI3_RERANK_GPU: $AI3_RERANK_GPU"
echo "  AI3_WORKER_GPUS: $AI3_WORKER_GPUS"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}ERROR: python3 not found${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python3 found${NC}"

# Check CUDA
if ! command -v nvidia-smi &> /dev/null; then
    echo -e "${YELLOW}WARNING: nvidia-smi not found, GPU pinning may not work${NC}"
else
    echo -e "${GREEN}✓ CUDA available${NC}"
    nvidia-smi --query-gpu=index,name,memory.free --format=csv,noheader,nounits | while IFS=',' read -r idx name mem; do
        echo "  GPU $idx: $name (${mem}MB free)"
    done
fi

echo ""
echo "=========================================="
echo "Starting Services"
echo "=========================================="

# Kill oude processen
echo -e "${YELLOW}Stopping old processes...${NC}"
pkill -f "uvicorn.*app:app.*9000" 2>/dev/null || true
pkill -f "uvicorn.*doc_analyzer_service:app.*9100" 2>/dev/null || true
pkill -f "uvicorn.*reranker_service:app.*9200" 2>/dev/null || true
sleep 2

# ============================================
# 1. DataFactory (:9000) - Met GPU 0 pinning
# ============================================
echo ""
echo -e "${GREEN}[1/3] Starting DataFactory on :$DATAFACTORY_PORT (GPU $AI3_EMBED_GPU)${NC}"

CUDA_VISIBLE_DEVICES=$AI3_EMBED_GPU nohup python3 -m uvicorn app:app \
    --host 0.0.0.0 \
    --port $DATAFACTORY_PORT \
    --log-level info \
    > "$LOG_DIR/datafactory.log" 2>&1 &

DATAFACTORY_PID=$!
echo "  PID: $DATAFACTORY_PID"
echo "  Log: $LOG_DIR/datafactory.log"
echo "  GPU: $AI3_EMBED_GPU (CUDA_VISIBLE_DEVICES)"

# Wacht op startup
sleep 3

if ! ps -p $DATAFACTORY_PID > /dev/null; then
    echo -e "${RED}ERROR: DataFactory failed to start${NC}"
    tail -n 20 "$LOG_DIR/datafactory.log"
    exit 1
fi

# Check health
if curl -s http://localhost:$DATAFACTORY_PORT/health > /dev/null; then
    echo -e "${GREEN}  ✓ DataFactory healthy${NC}"
else
    echo -e "${YELLOW}  ⚠ DataFactory health check failed (maar draait wel)${NC}"
fi

# ============================================
# 2. Doc Analyzer (:9100) - Geen GPU pinning (gebruikt AI-4)
# ============================================
echo ""
echo -e "${GREEN}[2/3] Starting Doc Analyzer on :$DOC_ANALYZER_PORT${NC}"

nohup python3 -m uvicorn doc_analyzer_service:app \
    --host 0.0.0.0 \
    --port $DOC_ANALYZER_PORT \
    --log-level info \
    > "$LOG_DIR/doc_analyzer.log" 2>&1 &

DOC_ANALYZER_PID=$!
echo "  PID: $DOC_ANALYZER_PID"
echo "  Log: $LOG_DIR/doc_analyzer.log"
echo "  GPU: None (routes to AI-4)"

sleep 3

if ! ps -p $DOC_ANALYZER_PID > /dev/null; then
    echo -e "${RED}ERROR: Doc Analyzer failed to start${NC}"
    tail -n 20 "$LOG_DIR/doc_analyzer.log"
    exit 1
fi

if curl -s http://localhost:$DOC_ANALYZER_PORT/health > /dev/null; then
    echo -e "${GREEN}  ✓ Doc Analyzer healthy${NC}"
else
    echo -e "${YELLOW}  ⚠ Doc Analyzer health check failed${NC}"
fi

# ============================================
# 3. Reranker (:9200) - Met GPU 1 pinning
# ============================================
echo ""
echo -e "${GREEN}[3/3] Starting Reranker on :$RERANKER_PORT (GPU $AI3_RERANK_GPU)${NC}"

CUDA_VISIBLE_DEVICES=$AI3_RERANK_GPU nohup python3 -m uvicorn reranker_service:app \
    --host 0.0.0.0 \
    --port $RERANKER_PORT \
    --log-level info \
    > "$LOG_DIR/reranker.log" 2>&1 &

RERANKER_PID=$!
echo "  PID: $RERANKER_PID"
echo "  Log: $LOG_DIR/reranker.log"
echo "  GPU: $AI3_RERANK_GPU (CUDA_VISIBLE_DEVICES)"

sleep 3

if ! ps -p $RERANKER_PID > /dev/null; then
    echo -e "${RED}ERROR: Reranker failed to start${NC}"
    tail -n 20 "$LOG_DIR/reranker.log"
    exit 1
fi

if curl -s http://localhost:$RERANKER_PORT/health > /dev/null; then
    echo -e "${GREEN}  ✓ Reranker healthy${NC}"
else
    echo -e "${YELLOW}  ⚠ Reranker health check failed${NC}"
fi

# ============================================
# Summary
# ============================================
echo ""
echo "=========================================="
echo -e "${GREEN}AI-3 Services Started Successfully!${NC}"
echo "=========================================="
echo ""
echo "Services:"
echo "  • DataFactory    http://localhost:$DATAFACTORY_PORT    (PID: $DATAFACTORY_PID, GPU: $AI3_EMBED_GPU)"
echo "  • Doc Analyzer   http://localhost:$DOC_ANALYZER_PORT   (PID: $DOC_ANALYZER_PID, GPU: AI-4)"
echo "  • Reranker       http://localhost:$RERANKER_PORT       (PID: $RERANKER_PID, GPU: $AI3_RERANK_GPU)"
echo ""
echo "Logs:"
echo "  • tail -f $LOG_DIR/datafactory.log"
echo "  • tail -f $LOG_DIR/doc_analyzer.log"
echo "  • tail -f $LOG_DIR/reranker.log"
echo ""
echo "Stop all:"
echo "  pkill -f 'uvicorn.*app:app.*9000'"
echo "  pkill -f 'uvicorn.*doc_analyzer_service:app.*9100'"
echo "  pkill -f 'uvicorn.*reranker_service:app.*9200'"
echo ""
echo "Test endpoints:"
echo "  curl http://localhost:$DATAFACTORY_PORT/health"
echo "  curl http://localhost:$DOC_ANALYZER_PORT/health"
echo "  curl http://localhost:$RERANKER_PORT/health"
echo ""
echo "=========================================="
