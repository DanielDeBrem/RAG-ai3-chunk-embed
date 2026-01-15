#!/bin/bash
# Test Local Pipeline - Jaarrekening Ingest & Search
set -e

echo "=========================================="
echo "AI-3 Pipeline Local Test"
echo "Test: Jaarrekening 2017 De Brem (1.2MB)"
echo "=========================================="

# Kleuren
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

ROOT_DIR="/home/daniel/Projects/RAG-ai3-chunk-embed"
PDF_FILE="$ROOT_DIR/data/Jaarrekening 2017 De Brem Holding BV.pdf"
LOG_DIR="$ROOT_DIR/logs"

mkdir -p "$LOG_DIR"

cd "$ROOT_DIR"

# Check PDF bestaat
if [ ! -f "$PDF_FILE" ]; then
    echo -e "${RED}ERROR: PDF niet gevonden: $PDF_FILE${NC}"
    exit 1
fi

echo -e "${BLUE}PDF gevonden:${NC} $(ls -lh "$PDF_FILE" | awk '{print $9, $5}')"
echo ""

# === STAP 1: Start services ===
echo "=========================================="
echo "STAP 1: Start Services"
echo "=========================================="

# Stop oude processen
echo -e "${YELLOW}Stopping old processes...${NC}"
pkill -f "uvicorn.*9000" 2>/dev/null || true
pkill -f "ollama serve" 2>/dev/null || true
sleep 2

# Start 6 Ollama instances (GPU 2-7)
echo -e "${GREEN}Starting 6 Ollama instances (GPU 2-7)...${NC}"
for i in {2..7}; do
    PORT=$((11434 + i - 2))
    echo "  GPU $i -> port $PORT"
    CUDA_VISIBLE_DEVICES=$i \
    OLLAMA_HOST="0.0.0.0:$PORT" \
    OLLAMA_KEEP_ALIVE="30m" \
        nohup ollama serve > "$LOG_DIR/ollama_gpu${i}.log" 2>&1 &
    sleep 0.5
done

echo -e "${GREEN}Waiting for Ollama instances to start...${NC}"
sleep 5

# Check Ollama instances
echo ""
echo "Ollama Status:"
ALL_OK=true
for i in {0..5}; do
    PORT=$((11434 + i))
    if curl -s "http://localhost:$PORT/api/tags" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Ollama GPU $((i+2)) (port $PORT)"
    else
        echo -e "  ${RED}✗${NC} Ollama GPU $((i+2)) (port $PORT) FAILED"
        ALL_OK=false
    fi
done

if ! $ALL_OK; then
    echo -e "${RED}ERROR: Not all Ollama instances started${NC}"
    exit 1
fi

# Start DataFactory (GPU 0)
echo ""
echo -e "${GREEN}Starting DataFactory (GPU 0)...${NC}"

source "$ROOT_DIR/.venv/bin/activate"

CUDA_VISIBLE_DEVICES=0 \
OLLAMA_MULTI_GPU=true \
OLLAMA_NUM_INSTANCES=6 \
OLLAMA_BASE_PORT=11434 \
AI4_LLM70_ENABLED=false \
AI4_FALLBACK_TO_HEURISTICS=true \
    nohup uvicorn app:app --host 0.0.0.0 --port 9000 \
    > "$LOG_DIR/datafactory_test.log" 2>&1 &

DATAFACTORY_PID=$!
echo "  PID: $DATAFACTORY_PID"

sleep 5

# Check DataFactory
if ! ps -p $DATAFACTORY_PID > /dev/null 2>&1; then
    echo -e "${RED}ERROR: DataFactory failed to start${NC}"
    echo "Last 30 lines of log:"
    tail -n 30 "$LOG_DIR/datafactory_test.log"
    exit 1
fi

if curl -s http://localhost:9000/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ DataFactory healthy${NC}"
else
    echo -e "${YELLOW}⚠ DataFactory health check failed (but running)${NC}"
fi

# GPU Status
echo ""
echo "GPU Status:"
nvidia-smi --query-gpu=index,memory.used,temperature.gpu \
    --format=csv,noheader,nounits | while IFS=, read -r idx used temp; do
    echo "  GPU $idx: ${used}MB used, ${temp}°C"
done

echo ""
echo -e "${GREEN}Services started successfully!${NC}"
sleep 2

# === STAP 2: Ingest via File Upload (met OCR!) ===
echo ""
echo "=========================================="
echo "STAP 2: Ingest Document via File Upload API"
echo "=========================================="

echo "Ingesting document with automatic OCR..."
echo "  Document: Jaarrekening 2017 De Brem.pdf"
echo "  Project: test:pipeline_test"
echo "  Type: jaarrekening"
echo "  Chunk strategy: page_plus_table_aware"
echo "  OCR: automatic (smart detection)"
echo ""

# Ingest via POST /v1/rag/ingest/file (uses OCR in app.py!)
INGEST_RESPONSE=$(curl -s -X POST "http://localhost:9000/v1/rag/ingest/file" \
  -F "project_id=test:pipeline_test" \
  -F "document_type=jaarrekening" \
  -F "doc_id=Jaarrekening 2017 De Brem.pdf" \
  -F "chunk_strategy=page_plus_table_aware" \
  -F "chunk_overlap=200" \
  -F "file=@$PDF_FILE")

echo "Ingest Response:"
echo "$INGEST_RESPONSE" | jq .

CHUNKS_ADDED=$(echo "$INGEST_RESPONSE" | jq -r '.chunks_added // 0')

if [ "$CHUNKS_ADDED" -gt 0 ]; then
    echo -e "${GREEN}✓ Ingest successful: $CHUNKS_ADDED chunks added${NC}"
else
    echo -e "${RED}✗ Ingest failed or no chunks added${NC}"
    echo "Check logs: tail -f $LOG_DIR/datafactory_test.log"
    exit 1
fi

# Wait for processing (OCR takes longer!)
echo ""
echo "Waiting for OCR + enrichment + embedding (this takes ~1-2 min for 41 pages)..."
sleep 60

# === STAP 4: Test Search ===
echo ""
echo "=========================================="
echo "STAP 4: Test Search Queries"
echo "=========================================="

# Test query 1: Balans
echo ""
echo -e "${BLUE}Query 1: Wat staat er op de balans?${NC}"
SEARCH_RESPONSE_1=$(curl -s -X POST "http://localhost:9000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "test",
    "project_id": "pipeline_test",
    "query": "Wat staat er op de balans?",
    "document_type": "jaarrekening",
    "top_k": 3
  }')

echo "$SEARCH_RESPONSE_1" | jq -r '.chunks[] | "Score: \(.score | tonumber | . * 100 | floor / 100)\nText: \(.text[:200])...\n"'

# Test query 2: Financiële positie
echo ""
echo -e "${BLUE}Query 2: Wat is de financiële positie van het bedrijf?${NC}"
SEARCH_RESPONSE_2=$(curl -s -X POST "http://localhost:9000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "test",
    "project_id": "pipeline_test",
    "query": "Wat is de financiële positie van het bedrijf?",
    "document_type": "jaarrekening",
    "top_k": 3
  }')

echo "$SEARCH_RESPONSE_2" | jq -r '.chunks[] | "Score: \(.score | tonumber | . * 100 | floor / 100)\nText: \(.text[:200])...\n"'

# === STAP 5: Check Logs ===
echo ""
echo "=========================================="
echo "STAP 5: Log Analysis"
echo "=========================================="

echo ""
echo "DataFactory log (last 20 lines):"
tail -n 20 "$LOG_DIR/datafactory_test.log"

echo ""
echo "Enriched chunks saved to:"
ls -lh data/enriched_*.json 2>/dev/null | tail -1 || echo "No enriched files found"

# === Summary ===
echo ""
echo "=========================================="
echo -e "${GREEN}TEST COMPLETED${NC}"
echo "=========================================="
echo ""
echo "Services:"
echo "  DataFactory: http://localhost:9000"
echo "  Ollama: 6 instances on GPU 2-7"
echo ""
echo "Results:"
echo "  Chunks ingested: $CHUNKS_ADDED"
echo "  Searches: 2 test queries executed"
echo ""
echo "Logs:"
echo "  DataFactory: $LOG_DIR/datafactory_test.log"
echo "  Ollama: $LOG_DIR/ollama_gpu*.log"
echo ""
echo "GPU Status:"
nvidia-smi --query-gpu=index,memory.used,temperature.gpu \
    --format=csv,noheader,nounits | while IFS=, read -r idx used temp; do
    echo "  GPU $idx: ${used}MB used, ${temp}°C"
done
echo ""
echo -e "${YELLOW}Services blijven draaien voor verdere tests.${NC}"
echo "Stop met: pkill -f 'uvicorn.*9000' && pkill -f 'ollama serve'"
