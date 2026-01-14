#!/usr/bin/env bash
#
# Enable Multi-GPU Enrichment
# 
# Dit script:
# 1. Start 6 Ollama instances (poorten 11434-11439), elk op eigen GPU
# 2. Herstart DataFactory met OLLAMA_MULTI_GPU=true
# 3. Verdeelt enrichment load over alle GPU's
#
set -euo pipefail

ROOT_DIR="$HOME/Projects/RAG-ai3-chunk-embed"
VENV_DIR="$ROOT_DIR/.venv"
LOG_DIR="$ROOT_DIR/logs"

# Kleuren
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_status() { echo -e "${BLUE}[STATUS]${NC} $1"; }
echo_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
echo_err() { echo -e "${RED}[ERROR]${NC} $1"; }
echo_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

echo "=========================================="
echo "  Enable Multi-GPU Enrichment"
echo "=========================================="
echo ""

cd "$ROOT_DIR"

# === STAP 1: Stop oude Ollama ROBUUST ===
echo "=== STAP 1: Stop systemd Ollama (robuust) ==="
echo_status "Stopping systemd ollama..."
sudo systemctl stop ollama 2>/dev/null || true
sleep 1

echo_status "Killing alle Ollama processen..."
pkill -9 -f "ollama" 2>/dev/null || true
sleep 2

# Verificatie: check of processen echt weg zijn
echo_status "Verificatie: check GPU processen..."
MAX_RETRIES=10
RETRY=0
while [ $RETRY -lt $MAX_RETRIES ]; do
    GPU_PIDS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | wc -l)
    if [ "$GPU_PIDS" -eq 0 ]; then
        echo_ok "Alle GPU processen gestopt"
        break
    fi
    
    RETRY=$((RETRY + 1))
    echo_warn "Nog $GPU_PIDS processen actief, retry $RETRY/$MAX_RETRIES..."
    
    # Extra agressief: kill alle GPU processen
    nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | while read pid; do
        [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
    done
    
    sleep 2
done

if [ $RETRY -eq $MAX_RETRIES ]; then
    echo_err "Kon niet alle GPU processen stoppen na $MAX_RETRIES pogingen"
    echo "Nog actieve processen:"
    nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
    exit 1
fi

# === STAP 2: Start Multi-Ollama ===
echo ""
echo "=== STAP 2: Start 6 Ollama instances ==="

OLLAMA_MODELS="/usr/share/ollama/.ollama"
BASE_PORT=11434
NUM_INSTANCES=6

mkdir -p "$LOG_DIR/ollama"

echo_status "Starting $NUM_INSTANCES Ollama instances (sharing models from $OLLAMA_MODELS)..."

for i in $(seq 0 $((NUM_INSTANCES-1))); do
    PORT=$((BASE_PORT + i))
    LOG_FILE="$LOG_DIR/ollama/ollama_gpu${i}.log"
    
    echo "  GPU $i → port $PORT"
    
    # Start Ollama met specifieke GPU en shared model directory
    CUDA_VISIBLE_DEVICES=$i \
    OLLAMA_HOST="0.0.0.0:$PORT" \
    OLLAMA_MODELS="$OLLAMA_MODELS/models" \
        nohup ollama serve > "$LOG_FILE" 2>&1 &
    
    sleep 0.5
done

echo ""
echo_status "Waiting for instances to start..."
sleep 5

# Check status
echo ""
echo_ok "Instance Status:"
ALL_OK=true
for i in $(seq 0 $((NUM_INSTANCES-1))); do
    PORT=$((BASE_PORT + i))
    if curl -s "http://localhost:$PORT/api/tags" > /dev/null 2>&1; then
        MODELS=$(curl -s "http://localhost:$PORT/api/tags" | jq -r '.models | length' 2>/dev/null || echo "?")
        echo "  ✓ GPU $i (port $PORT): $MODELS models"
    else
        echo "  ✗ GPU $i (port $PORT): FAILED"
        ALL_OK=false
    fi
done

if ! $ALL_OK; then
    echo_err "Sommige Ollama instances konden niet starten"
    echo "Check logs: tail -f $LOG_DIR/ollama/ollama_gpu*.log"
    exit 1
fi

# === STAP 3: Herstart DataFactory ===
echo ""
echo "=== STAP 3: Herstart DataFactory met Multi-GPU ==="

# Kill datafactory
echo_status "Stop DataFactory..."
lsof -ti:9000 2>/dev/null | xargs kill 2>/dev/null || true
sleep 2

# Start met OLLAMA_MULTI_GPU=true
echo_status "Start DataFactory met OLLAMA_MULTI_GPU=true..."
source "$VENV_DIR/bin/activate"

OLLAMA_MODELS="$OLLAMA_MODELS/models" \
OLLAMA_MULTI_GPU=true \
OLLAMA_BASE_PORT=11434 \
OLLAMA_NUM_INSTANCES=6 \
    nohup uvicorn app:app \
    --host 0.0.0.0 --port 9000 \
    --timeout-keep-alive 7200 \
    --timeout-graceful-shutdown 30 \
    --limit-concurrency 1000 \
    --backlog 2048 > "$LOG_DIR/datafactory_9000.log" 2>&1 &

sleep 3

# Check DataFactory
if curl -s "http://localhost:9000/health" > /dev/null 2>&1; then
    echo_ok "DataFactory beschikbaar"
else
    echo_err "DataFactory kon niet starten"
    echo "Check logs: tail -f $LOG_DIR/datafactory_9000.log"
    exit 1
fi

# === STAP 4: Samenvatting ===
echo ""
echo "=========================================="
echo_ok "Multi-GPU Enrichment ENABLED!"
echo "=========================================="
echo ""
echo "Ollama instances:"
for i in $(seq 0 $((NUM_INSTANCES-1))); do
    PORT=$((BASE_PORT + i))
    echo "  GPU $i: http://localhost:$PORT (voor worker $i)"
done
echo ""
echo "DataFactory:"
echo "  http://localhost:9000 (OLLAMA_MULTI_GPU=true)"
echo ""
echo "Logs:"
echo "  Ollama: tail -f $LOG_DIR/ollama/ollama_gpu*.log"
echo "  DataFactory: tail -f $LOG_DIR/datafactory_9000.log"
echo ""
echo "GPU Status:"
nvidia-smi --query-gpu=index,temperature.gpu,memory.used --format=csv
echo ""
echo "Nu worden enrichment requests verdeeld over 6 GPU's!"
echo "GPU1 zal niet meer zo heet worden (93°C → ~60-70°C per GPU)"
