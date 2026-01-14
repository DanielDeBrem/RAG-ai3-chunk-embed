#!/usr/bin/env bash
#
# AI-3 Service Starter - Robuuste versie
# 
# Fixes voor genoteerde blunders:
# - Blunder 1: Expliciet 70B model laden
# - Blunder 2: Model status checken met ollama ps
# - Blunder 3: OLLAMA_MODELS path correct zetten
#
set -euo pipefail

ROOT_DIR="$HOME/Projects/RAG-ai3-chunk-embed"
VENV_DIR="$ROOT_DIR/.venv"
LOG_DIR="$ROOT_DIR/logs"

# === CRITICAL: Ollama model locatie ===
export OLLAMA_MODELS="/usr/share/ollama/.ollama/models"

# Default model voor analyse/enrichment
DEFAULT_LLM_MODEL="${LLM_MODEL:-llama3.1:70b}"

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

echo "========================================"
echo "  AI-3 Service Starter (Robuust)"
echo "========================================"
echo "Project: $ROOT_DIR"
echo "OLLAMA_MODELS: $OLLAMA_MODELS"
echo "Default LLM: $DEFAULT_LLM_MODEL"
echo ""

# === Validatie ===
if [ ! -d "$ROOT_DIR" ]; then
  echo_err "$ROOT_DIR bestaat niet"
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo_err "venv niet gevonden op $VENV_DIR"
  exit 1
fi

cd "$ROOT_DIR"
source "$VENV_DIR/bin/activate"
mkdir -p "$LOG_DIR"

# === Helper functies ===

kill_port() {
  local PORT="$1"
  if command -v lsof >/dev/null 2>&1; then
    local PIDS
    PIDS=$(lsof -ti:"$PORT" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
      echo_status "Kill processen op poort $PORT: $PIDS"
      kill $PIDS 2>/dev/null || true
      sleep 1
    fi
  fi
}

wait_for_service() {
  local url=$1
  local name=$2
  local timeout=${3:-60}
  local count=0
  
  echo_status "Wacht op $name..."
  while ! curl -s "$url" > /dev/null 2>&1; do
    sleep 1
    count=$((count + 1))
    if [ $count -ge $timeout ]; then
      echo_err "Timeout wachten op $name ($url)"
      return 1
    fi
  done
  echo_ok "$name beschikbaar"
  return 0
}

check_gpu_status() {
  echo_status "GPU Status:"
  nvidia-smi --query-gpu=index,memory.used,memory.free,temperature.gpu \
    --format=csv,noheader,nounits 2>/dev/null | while IFS=, read -r idx used free temp; do
    echo "  GPU $idx: ${used}MB used, ${free}MB free, ${temp}°C"
  done
}

# === STAP 1: Stop oude processen ===
echo ""
echo "=== STAP 1: Cleanup oude processen ==="
kill_port 8000
kill_port 9000
kill_port 9100
kill_port 9200

# === STAP 2: Start Ollama met correcte OLLAMA_MODELS ===
echo ""
echo "=== STAP 2: Start Ollama ==="

# Check of Ollama al draait
if pgrep -x "ollama" > /dev/null; then
  echo_warn "Ollama draait al, checken of OLLAMA_MODELS correct is..."
else
  echo_status "Starten Ollama serve met OLLAMA_MODELS=$OLLAMA_MODELS"
  OLLAMA_MODELS="$OLLAMA_MODELS" ollama serve > "$LOG_DIR/ollama.log" 2>&1 &
  sleep 3
fi

# Wacht tot Ollama beschikbaar is
if ! wait_for_service "http://localhost:11434/api/tags" "Ollama" 30; then
  echo_err "Ollama kon niet starten!"
  exit 1
fi

# === STAP 3: Check beschikbare models (FIX Blunder 3) ===
echo ""
echo "=== STAP 3: Check Ollama models ==="
echo_status "Beschikbare models:"
OLLAMA_MODELS="$OLLAMA_MODELS" ollama list | head -10

# Check of het gewenste model beschikbaar is
if ! OLLAMA_MODELS="$OLLAMA_MODELS" ollama list | grep -q "$DEFAULT_LLM_MODEL"; then
  echo_err "Model $DEFAULT_LLM_MODEL niet gevonden!"
  echo_status "Beschikbare models:"
  OLLAMA_MODELS="$OLLAMA_MODELS" ollama list
  echo_warn "Ga door zonder model warmup..."
else
  echo_ok "Model $DEFAULT_LLM_MODEL beschikbaar"
fi

# === STAP 4: Warmup 70B model (FIX Blunder 1) ===
echo ""
echo "=== STAP 4: Warmup LLM model ==="

# Check huidige model status (FIX Blunder 2)
echo_status "Huidige model status (ollama ps):"
OLLAMA_MODELS="$OLLAMA_MODELS" ollama ps

# Check of model al geladen is
if OLLAMA_MODELS="$OLLAMA_MODELS" ollama ps | grep -q "$DEFAULT_LLM_MODEL"; then
  echo_ok "Model $DEFAULT_LLM_MODEL is al geladen"
else
  echo_status "Laden $DEFAULT_LLM_MODEL (dit kan even duren)..."
  
  # Warmup met kleine prompt
  WARMUP_RESULT=$(curl -s http://localhost:11434/api/generate \
    -d "{\"model\":\"$DEFAULT_LLM_MODEL\",\"prompt\":\"Hello\",\"stream\":false}" \
    --max-time 120 2>/dev/null || echo '{"error":"timeout"}')
  
  if echo "$WARMUP_RESULT" | grep -q "error"; then
    echo_warn "Model warmup mislukt: $WARMUP_RESULT"
    echo_warn "Doorgaan, model wordt geladen bij eerste request"
  else
    echo_ok "Model $DEFAULT_LLM_MODEL geladen"
  fi
fi

# Bevestig model status
echo_status "Model status na warmup:"
OLLAMA_MODELS="$OLLAMA_MODELS" ollama ps

# === STAP 5: Check GPU status ===
echo ""
echo "=== STAP 5: GPU Status na model load ==="
check_gpu_status

# === STAP 6: Start Python services ===
echo ""
echo "=== STAP 6: Start Python services ==="

# Embedding Service (port 8000)
echo_status "Start embedding_service op poort 8000..."
OLLAMA_MODELS="$OLLAMA_MODELS" nohup uvicorn embedding_service:app \
  --host 0.0.0.0 --port 8000 > "$LOG_DIR/embedding_8000.log" 2>&1 &
EMBED_PID=$!
echo "  PID: $EMBED_PID"

# DataFactory (port 9000) - LANGE TIMEOUTS voor grote PDF's
echo_status "Start datafactory app op poort 9000..."
OLLAMA_MODELS="$OLLAMA_MODELS" nohup uvicorn app:app \
  --host 0.0.0.0 --port 9000 \
  --timeout-keep-alive 7200 \
  --timeout-graceful-shutdown 30 \
  --limit-concurrency 1000 \
  --backlog 2048 > "$LOG_DIR/datafactory_9000.log" 2>&1 &
DATA_PID=$!
echo "  PID: $DATA_PID"

# Doc Analyzer (port 9100) - LANGE TIMEOUTS voor grote PDF analyse (70B model)
echo_status "Start doc_analyzer_service op poort 9100..."
OLLAMA_MODELS="$OLLAMA_MODELS" nohup uvicorn doc_analyzer_service:app \
  --host 0.0.0.0 --port 9100 \
  --timeout-keep-alive 7200 \
  --timeout-graceful-shutdown 30 \
  --limit-concurrency 1000 \
  --backlog 2048 > "$LOG_DIR/analyzer_9100.log" 2>&1 &
ANALYZER_PID=$!
echo "  PID: $ANALYZER_PID"

# Reranker (port 9200)
echo_status "Start reranker_service op poort 9200..."
OLLAMA_MODELS="$OLLAMA_MODELS" nohup uvicorn reranker_service:app \
  --host 0.0.0.0 --port 9200 > "$LOG_DIR/reranker_9200.log" 2>&1 &
RERANK_PID=$!
echo "  PID: $RERANK_PID"

# === STAP 7: Wacht op services en health checks ===
echo ""
echo "=== STAP 7: Health checks ==="
sleep 5

ALL_OK=true

if wait_for_service "http://localhost:8000/health" "Embedding Service" 30; then
  curl -s http://localhost:8000/health | jq -c '.' 2>/dev/null || true
else
  ALL_OK=false
fi

if wait_for_service "http://localhost:9000/health" "DataFactory" 30; then
  curl -s http://localhost:9000/health | jq -c '.' 2>/dev/null || true
else
  ALL_OK=false
fi

if wait_for_service "http://localhost:9100/health" "Doc Analyzer" 30; then
  curl -s http://localhost:9100/health | jq -c '.' 2>/dev/null || true
else
  ALL_OK=false
fi

if wait_for_service "http://localhost:9200/health" "Reranker" 30; then
  curl -s http://localhost:9200/health | jq -c '.' 2>/dev/null || true
else
  ALL_OK=false
fi

# === STAP 8: Samenvatting ===
echo ""
echo "========================================"
if $ALL_OK; then
  echo_ok "Alle services gestart!"
else
  echo_warn "Sommige services konden niet starten"
fi
echo "========================================"
echo ""
echo "Lokale endpoints:"
echo "  http://localhost:8000  (Embedding Service)"
echo "  http://localhost:9000  (DataFactory)"
echo "  http://localhost:9100  (Doc Analyzer)"
echo "  http://localhost:9200  (Reranker)"
echo "  http://localhost:11434 (Ollama)"
echo ""
echo "Externe toegang (AI-4 via LAN):"
echo "  http://10.0.1.44:8000  (Embedding)"
echo "  http://10.0.1.44:9000  (DataFactory)"
echo "  http://10.0.1.44:9100  (Analyzer)"
echo "  http://10.0.1.44:9200  (Reranker)"
echo "  http://10.0.1.44:11434 (Ollama)"
echo ""
echo "Logs: $LOG_DIR"
echo "Model status: OLLAMA_MODELS=$OLLAMA_MODELS ollama ps"
echo ""

# Finale GPU status
check_gpu_status
