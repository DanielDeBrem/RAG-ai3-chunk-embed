#!/bin/bash
# Test Large PDF - Taxatie 45MB Stress Test
set -e

echo "=========================================="
echo "AI-3 Pipeline STRESS TEST"
echo "Test: Taxatierapport 45MB (OCR + Parallel)"
echo "=========================================="

# Kleuren
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

ROOT_DIR="/home/daniel/Projects/RAG-ai3-chunk-embed"
PDF_FILE="$ROOT_DIR/data/20251224 Taxatierapport Camping de Brem 2025.pdf"
LOG_DIR="$ROOT_DIR/logs"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

# Check PDF bestaat
if [ ! -f "$PDF_FILE" ]; then
    echo -e "${RED}ERROR: PDF niet gevonden: $PDF_FILE${NC}"
    exit 1
fi

PDF_SIZE=$(ls -lh "$PDF_FILE" | awk '{print $5}')
echo -e "${BLUE}PDF gevonden:${NC} $PDF_SIZE"
echo ""

# Services should already be running from previous test
echo "=========================================="
echo "Checking Services"
echo "=========================================="

# Check DataFactory
if curl -s http://localhost:9000/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ DataFactory running${NC}"
else
    echo -e "${RED}✗ DataFactory not running - start services first!${NC}"
    echo "Run: ./test_pipeline_local.sh first"
    exit 1
fi

# Check Ollama
OLLAMA_COUNT=0
for i in {0..5}; do
    PORT=$((11434 + i))
    if curl -s "http://localhost:$PORT/api/tags" > /dev/null 2>&1; then
        OLLAMA_COUNT=$((OLLAMA_COUNT + 1))
    fi
done

echo -e "${GREEN}✓ $OLLAMA_COUNT Ollama instances running${NC}"

if [ $OLLAMA_COUNT -lt 6 ]; then
    echo -e "${YELLOW}⚠ Not all Ollama instances running (expected 6, got $OLLAMA_COUNT)${NC}"
fi

# GPU Status
echo ""
echo "GPU Status (before):"
nvidia-smi --query-gpu=index,memory.used,temperature.gpu \
    --format=csv,noheader,nounits | while IFS=, read -r idx used temp; do
    echo "  GPU $idx: ${used}MB used, ${temp}°C"
done

echo ""
echo "=========================================="
echo "Ingesting 45MB Taxatie PDF"
echo "=========================================="

START_TIME=$(date +%s)

echo "Starting ingest..."
echo "  File: Taxatierapport Camping de Brem 2025.pdf"
echo "  Size: $PDF_SIZE"
echo "  Project: test:taxatie_stress"
echo "  Chunk strategy: page_plus_table_aware"
echo "  OCR: automatic detection"
echo ""
echo -e "${YELLOW}This may take 3-5 minutes for a 45MB PDF...${NC}"
echo ""

# Ingest via file upload
INGEST_RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "http://localhost:9000/v1/rag/ingest/file" \
  -F "project_id=test:taxatie_stress" \
  -F "document_type=taxatierapport" \
  -F "doc_id=Taxatierapport 2025.pdf" \
  -F "chunk_strategy=page_plus_table_aware" \
  -F "chunk_overlap=200" \
  -F "file=@$PDF_FILE" \
  --max-time 600)

HTTP_CODE=$(echo "$INGEST_RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2)
RESPONSE_BODY=$(echo "$INGEST_RESPONSE" | grep -v "HTTP_CODE:")

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo "Ingest Response (HTTP $HTTP_CODE):"
echo "$RESPONSE_BODY" | jq . 2>/dev/null || echo "$RESPONSE_BODY"

CHUNKS_ADDED=$(echo "$RESPONSE_BODY" | jq -r '.chunks_added // 0' 2>/dev/null || echo "0")

echo ""
if [ "$CHUNKS_ADDED" -gt 0 ]; then
    echo -e "${GREEN}✓ Ingest successful!${NC}"
    echo "  Chunks: $CHUNKS_ADDED"
    echo "  Duration: ${DURATION}s ($(date -u -d @${DURATION} +%M:%S))"
    echo "  Throughput: ~$((45 / (DURATION / 60))) MB/min"
else
    echo -e "${RED}✗ Ingest failed or no chunks added${NC}"
    echo "Check logs: tail -f $LOG_DIR/datafactory_test.log"
    exit 1
fi

# Wait extra voor complete processing
echo ""
echo "Waiting 30s for complete processing..."
sleep 30

# === Test Search Queries ===
echo ""
echo "=========================================="
echo "Testing Search Queries"
echo "=========================================="

# Query 1
echo ""
echo -e "${BLUE}Query 1: Wat is de getaxeerde waarde van de camping?${NC}"
SEARCH_1=$(curl -s -X POST "http://localhost:9000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "test",
    "project_id": "taxatie_stress",
    "query": "Wat is de getaxeerde waarde van de camping?",
    "document_type": "taxatierapport",
    "top_k": 3
  }')

echo "$SEARCH_1" | jq -r '.chunks[] | "Score: \(.score | tonumber | . * 100 | floor / 100)\nPage: \(.text | match("\\[PAGE [0-9]+\\]") | .string)\nText: \(.text[0:150])...\n"'

# Query 2
echo ""
echo -e "${BLUE}Query 2: Welke risicos worden genoemd in het rapport?${NC}"
SEARCH_2=$(curl -s -X POST "http://localhost:9000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "test",
    "project_id": "taxatie_stress",
    "query": "Welke risicos worden genoemd?",
    "document_type": "taxatierapport",
    "top_k": 3
  }')

echo "$SEARCH_2" | jq -r '.chunks[] | "Score: \(.score | tonumber | . * 100 | floor / 100)\nPage: \(.text | match("\\[PAGE [0-9]+\\]") | .string)\nText: \(.text[0:150])...\n"'

# === Performance Analysis ===
echo ""
echo "=========================================="
echo "Performance Analysis"
echo "=========================================="

# Check enriched file
ENRICHED_FILE=$(ls -t data/enriched_Taxatierapport*.json 2>/dev/null | head -1)
if [ -f "$ENRICHED_FILE" ]; then
    ENRICHED_SIZE=$(ls -lh "$ENRICHED_FILE" | awk '{print $5}')
    CHUNK_COUNT=$(cat "$ENRICHED_FILE" | jq -r '.raw_chunks | length' 2>/dev/null || echo "unknown")
    
    echo "Enriched chunks file:"
    echo "  File: $(basename "$ENRICHED_FILE")"
    echo "  Size: $ENRICHED_SIZE"
    echo "  Chunks: $CHUNK_COUNT"
    
    # Sample first chunk
    echo ""
    echo "Sample chunk (first 300 chars):"
    cat "$ENRICHED_FILE" | jq -r '.raw_chunks[0][0:300]' 2>/dev/null || echo "Could not read"
fi

# GPU Status after
echo ""
echo "GPU Status (after):"
nvidia-smi --query-gpu=index,memory.used,temperature.gpu \
    --format=csv,noheader,nounits | while IFS=, read -r idx used temp; do
    echo "  GPU $idx: ${used}MB used, ${temp}°C"
done

# Log analysis
echo ""
echo "Last 30 lines of log:"
tail -n 30 "$LOG_DIR/datafactory_test.log"

# === Summary ===
echo ""
echo "=========================================="
echo -e "${GREEN}STRESS TEST COMPLETED${NC}"
echo "=========================================="
echo ""
echo "Input:"
echo "  PDF: 45MB, ~200+ pages"
echo "  Processing time: ${DURATION}s"
echo ""
echo "Output:"
echo "  Chunks created: $CHUNKS_ADDED"
echo "  OCR used: automatic (for low-text pages)"
echo "  Enrichment: 6x parallel LLM (GPU 2-7)"
echo "  Embedding: GPU 0"
echo ""
echo "Performance:"
echo "  Throughput: ~$((45 * 60 / DURATION)) MB/hour"
echo "  Time per chunk: ~$((DURATION / CHUNKS_ADDED))s"
echo ""
echo -e "${YELLOW}Services still running for more tests.${NC}"
echo "Stop with: pkill -f 'uvicorn.*9000' && pkill -f 'ollama serve'"
