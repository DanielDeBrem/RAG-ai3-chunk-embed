#!/usr/bin/env bash
#
# DEBUG PIPELINE - Stap voor stap testen van chunk-embed-rerank pipeline
#
# Gebruik:
#   ./debug_pipeline.sh          # Interactief menu
#   ./debug_pipeline.sh 1        # Start alleen Ollama
#   ./debug_pipeline.sh 2        # Start embedding_service
#   etc.
#
set -euo pipefail

ROOT_DIR="$HOME/Projects/RAG-ai3-chunk-embed"
VENV_DIR="$ROOT_DIR/.venv"
LOG_DIR="$ROOT_DIR/logs"

# Test document (pas dit aan naar je eigen test file)
TEST_DOC="${TEST_DOC:-$ROOT_DIR/corpus/test1.txt}"

# Kleuren
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

cd "$ROOT_DIR"
source "$VENV_DIR/bin/activate"
mkdir -p "$LOG_DIR"

echo_status() {
    echo -e "${BLUE}[STATUS]${NC} $1"
}

echo_ok() {
    echo -e "${GREEN}[OK]${NC} $1"
}

echo_err() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Check of een poort in gebruik is
check_port() {
    local port=$1
    if ss -tlnp | grep -q ":$port "; then
        return 0  # in gebruik
    else
        return 1  # vrij
    fi
}

# Wacht tot service beschikbaar is
wait_for_service() {
    local url=$1
    local timeout=${2:-30}
    local count=0
    
    echo_status "Wachten op $url ..."
    while ! curl -s "$url" > /dev/null 2>&1; do
        sleep 1
        count=$((count + 1))
        if [ $count -ge $timeout ]; then
            echo_err "Timeout wachten op $url"
            return 1
        fi
    done
    echo_ok "$url beschikbaar"
    return 0
}

# GPU status tonen
show_gpu_status() {
    echo ""
    echo "=== GPU STATUS ==="
    nvidia-smi --query-gpu=index,name,memory.used,memory.free,temperature.gpu,utilization.gpu \
        --format=csv,noheader,nounits | while IFS=, read -r idx name used free temp util; do
        echo "GPU $idx: ${used}MB used, ${free}MB free, ${temp}°C, ${util}% util"
    done
    echo ""
}

# Stop alle services
stop_all() {
    echo_status "Stoppen van alle services..."
    
    # Kill by port
    for port in 8000 9000 9100 9200; do
        if check_port $port; then
            local pids=$(lsof -ti:$port 2>/dev/null || true)
            if [ -n "$pids" ]; then
                echo_status "Kill processen op poort $port: $pids"
                kill $pids 2>/dev/null || true
            fi
        fi
    done
    
    # Ollama stoppen (optioneel)
    if pgrep -x "ollama" > /dev/null; then
        echo_warn "Ollama draait nog. Stoppen? (y/n)"
        read -r answer
        if [ "$answer" = "y" ]; then
            pkill -f "ollama serve" || true
            pkill -f "ollama runner" || true
            echo_ok "Ollama gestopt"
        fi
    fi
    
    sleep 2
    show_gpu_status
}

# STAP 0: Status check
step_status() {
    echo ""
    echo "=== PIPELINE STATUS ==="
    echo ""
    
    # Ollama
    if pgrep -x "ollama" > /dev/null; then
        echo_ok "Ollama: RUNNING"
        curl -s http://localhost:11434/api/tags 2>/dev/null | jq -r '.models[].name' 2>/dev/null | head -3 || echo "  (geen models geladen)"
    else
        echo_warn "Ollama: STOPPED"
    fi
    
    # Services checken
    for service in "embedding_service:8000" "datafactory:9000" "doc_analyzer:9100" "reranker:9200"; do
        local name="${service%%:*}"
        local port="${service##*:}"
        if check_port $port; then
            echo_ok "$name (port $port): RUNNING"
        else
            echo_warn "$name (port $port): STOPPED"
        fi
    done
    
    echo ""
    show_gpu_status
}

# STAP 1: Start Ollama
step1_ollama() {
    echo ""
    echo "=== STAP 1: OLLAMA STARTEN ==="
    echo ""
    
    if pgrep -f "ollama serve" > /dev/null; then
        echo_warn "Ollama serve draait al"
    else
        echo_status "Starten van ollama serve..."
        ollama serve > "$LOG_DIR/ollama.log" 2>&1 &
        sleep 3
    fi
    
    wait_for_service "http://localhost:11434/api/tags" 30
    
    # Check models
    echo_status "Beschikbare models:"
    curl -s http://localhost:11434/api/tags | jq -r '.models[].name' 2>/dev/null || echo "Geen models"
    
    # Pre-load 70B model (optioneel)
    echo ""
    echo_warn "Wil je llama3.1:70b pre-loaden? (Dit duurt even en claimt ~47GB VRAM) (y/n)"
    read -r answer
    if [ "$answer" = "y" ]; then
        echo_status "Pre-loading llama3.1:70b..."
        curl -s http://localhost:11434/api/generate -d '{"model":"llama3.1:70b","prompt":"test","stream":false}' > /dev/null 2>&1 &
        echo_ok "Model wordt geladen in achtergrond"
    fi
    
    show_gpu_status
}

# STAP 2: Start Embedding Service
step2_embedding() {
    echo ""
    echo "=== STAP 2: EMBEDDING SERVICE (port 8000) ==="
    echo ""
    
    if check_port 8000; then
        echo_warn "Port 8000 is al bezet"
        return
    fi
    
    echo_status "Starten van embedding_service..."
    nohup uvicorn embedding_service:app --host 0.0.0.0 --port 8000 \
        > "$LOG_DIR/embedding_8000.log" 2>&1 &
    
    wait_for_service "http://localhost:8000/health" 60
    
    # Test embedding
    echo_status "Test embedding..."
    local result=$(curl -s -X POST http://localhost:8000/embed \
        -H "Content-Type: application/json" \
        -d '{"texts": ["Dit is een test"]}')
    
    if echo "$result" | jq -e '.embeddings[0]' > /dev/null 2>&1; then
        local dim=$(echo "$result" | jq '.embeddings[0] | length')
        echo_ok "Embedding werkt! Dimensie: $dim"
    else
        echo_err "Embedding test gefaald: $result"
    fi
    
    show_gpu_status
}

# STAP 3: Start Doc Analyzer Service
step3_analyzer() {
    echo ""
    echo "=== STAP 3: DOC ANALYZER SERVICE (port 9100) ==="
    echo ""
    
    if check_port 9100; then
        echo_warn "Port 9100 is al bezet"
        return
    fi
    
    echo_status "Starten van doc_analyzer_service..."
    nohup uvicorn doc_analyzer_service:app --host 0.0.0.0 --port 9100 \
        > "$LOG_DIR/analyzer_9100.log" 2>&1 &
    
    wait_for_service "http://localhost:9100/health" 60
    
    echo_ok "Doc Analyzer Service gestart"
    echo_status "GPU status endpoint: http://localhost:9100/gpu/status"
    
    show_gpu_status
}

# STAP 4: Start Reranker Service
step4_reranker() {
    echo ""
    echo "=== STAP 4: RERANKER SERVICE (port 9200) ==="
    echo ""
    
    if check_port 9200; then
        echo_warn "Port 9200 is al bezet"
        return
    fi
    
    echo_status "Starten van reranker_service..."
    nohup uvicorn reranker_service:app --host 0.0.0.0 --port 9200 \
        > "$LOG_DIR/reranker_9200.log" 2>&1 &
    
    wait_for_service "http://localhost:9200/health" 60
    
    # Test reranker
    echo_status "Test reranker..."
    local result=$(curl -s -X POST http://localhost:9200/rerank \
        -H "Content-Type: application/json" \
        -d '{
            "query": "test vraag",
            "items": [
                {"id": "1", "text": "Dit is een test antwoord"},
                {"id": "2", "text": "Andere tekst"}
            ],
            "top_k": 2
        }')
    
    if echo "$result" | jq -e '.items' > /dev/null 2>&1; then
        echo_ok "Reranker werkt!"
        echo "$result" | jq '.items[] | "\(.id): score \(.score)"'
    else
        echo_err "Reranker test gefaald: $result"
    fi
    
    show_gpu_status
}

# STAP 5: Start DataFactory (main app)
step5_datafactory() {
    echo ""
    echo "=== STAP 5: DATAFACTORY (port 9000) ==="
    echo ""
    
    if check_port 9000; then
        echo_warn "Port 9000 is al bezet"
        return
    fi
    
    echo_status "Starten van DataFactory app..."
    nohup uvicorn app:app --host 0.0.0.0 --port 9000 \
        > "$LOG_DIR/datafactory_9000.log" 2>&1 &
    
    wait_for_service "http://localhost:9000/health" 60
    
    echo_ok "DataFactory gestart"
    
    # Check GPU status via app
    echo_status "DataFactory GPU status:"
    curl -s http://localhost:9000/gpu/status | jq '.' 2>/dev/null || echo "(geen response)"
    
    show_gpu_status
}

# STAP 6: Test Document Analyse (70B LLM)
step6_test_analyze() {
    echo ""
    echo "=== STAP 6: TEST DOCUMENT ANALYSE ==="
    echo ""
    
    if ! check_port 9100; then
        echo_err "Doc Analyzer niet beschikbaar op port 9100"
        return 1
    fi
    
    # Check of test document bestaat
    if [ ! -f "$TEST_DOC" ]; then
        echo_warn "Test document niet gevonden: $TEST_DOC"
        echo_status "Maak test document aan..."
        cat > "$TEST_DOC" << 'EOF'
Dit is een test document voor de RAG pipeline.

De klant heeft gevraagd om een offerte voor het volgende project:
- Website redesign
- SEO optimalisatie  
- Hosting voor 1 jaar

Contact: Jan de Vries
Email: jan@example.com
Telefoon: 06-12345678

Budget: €5.000 - €10.000
Deadline: Q1 2026
EOF
        echo_ok "Test document aangemaakt: $TEST_DOC"
    fi
    
    local doc_content=$(cat "$TEST_DOC")
    local filename=$(basename "$TEST_DOC")
    
    echo_status "Document analyse starten (async)..."
    echo_warn "Dit kan even duren - 70B model moet laden op GPU's"
    
    # Start async analyse
    local job_response=$(curl -s -X POST http://localhost:9100/analyze/async \
        -H "Content-Type: application/json" \
        -d "{
            \"document\": $(echo "$doc_content" | jq -Rs .),
            \"filename\": \"$filename\"
        }")
    
    local job_id=$(echo "$job_response" | jq -r '.job_id')
    
    if [ -z "$job_id" ] || [ "$job_id" = "null" ]; then
        echo_err "Kon geen job starten: $job_response"
        return 1
    fi
    
    echo_ok "Job gestart: $job_id"
    echo_status "Polling voor status..."
    
    # Poll status
    local status="pending"
    local count=0
    local max_wait=300  # 5 minuten max
    
    while [ "$status" != "completed" ] && [ "$status" != "failed" ]; do
        sleep 5
        count=$((count + 5))
        
        local status_response=$(curl -s "http://localhost:9100/analyze/status/$job_id")
        status=$(echo "$status_response" | jq -r '.status')
        local progress=$(echo "$status_response" | jq -r '.progress_pct')
        local message=$(echo "$status_response" | jq -r '.message')
        
        echo "  [$count s] Status: $status, Progress: $progress%, $message"
        show_gpu_status
        
        if [ $count -ge $max_wait ]; then
            echo_err "Timeout na $max_wait seconden"
            return 1
        fi
    done
    
    if [ "$status" = "completed" ]; then
        echo_ok "Analyse compleet!"
        curl -s "http://localhost:9100/analyze/status/$job_id" | jq '.result'
    else
        echo_err "Analyse gefaald"
        curl -s "http://localhost:9100/analyze/status/$job_id" | jq '.error'
    fi
}

# STAP 7: Test Ingest (chunking + embedding)
step7_test_ingest() {
    echo ""
    echo "=== STAP 7: TEST INGEST (CHUNKING + EMBEDDING) ==="
    echo ""
    
    if ! check_port 9000; then
        echo_err "DataFactory niet beschikbaar op port 9000"
        return 1
    fi
    
    # Check of test document bestaat
    if [ ! -f "$TEST_DOC" ]; then
        echo_err "Test document niet gevonden: $TEST_DOC"
        return 1
    fi
    
    local doc_content=$(cat "$TEST_DOC")
    local doc_id="test_$(date +%s)"
    
    echo_status "Ingest starten..."
    echo_warn "Dit doet: chunking → (optioneel) context enrichment → embedding → opslaan"
    
    local start_time=$(date +%s)
    
    local result=$(curl -s -X POST http://localhost:9000/v1/rag/ingest/text \
        -H "Content-Type: application/json" \
        -d "{
            \"project_id\": \"debug_test\",
            \"document_type\": \"generic\",
            \"doc_id\": \"$doc_id\",
            \"text\": $(echo "$doc_content" | jq -Rs .),
            \"metadata\": {\"source\": \"debug_pipeline\"}
        }")
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    if echo "$result" | jq -e '.chunks_added' > /dev/null 2>&1; then
        local chunks=$(echo "$result" | jq '.chunks_added')
        echo_ok "Ingest succesvol! Chunks toegevoegd: $chunks (duur: ${duration}s)"
        echo "$result" | jq '.'
    else
        echo_err "Ingest gefaald: $result"
    fi
    
    show_gpu_status
}

# STAP 8: Test Search (met reranking)
step8_test_search() {
    echo ""
    echo "=== STAP 8: TEST SEARCH (MET RERANKING) ==="
    echo ""
    
    if ! check_port 9000; then
        echo_err "DataFactory niet beschikbaar op port 9000"
        return 1
    fi
    
    echo_status "Search uitvoeren..."
    
    local result=$(curl -s -X POST http://localhost:9000/v1/rag/search \
        -H "Content-Type: application/json" \
        -d '{
            "project_id": "debug_test",
            "document_type": "generic",
            "question": "Wat is het budget?",
            "top_k": 3
        }')
    
    if echo "$result" | jq -e '.chunks' > /dev/null 2>&1; then
        local count=$(echo "$result" | jq '.chunks | length')
        echo_ok "Search succesvol! Resultaten: $count"
        echo "$result" | jq '.chunks[] | {chunk_id, score, text: .text[:100]}'
    else
        echo_err "Search gefaald: $result"
    fi
}

# Toon logs
show_logs() {
    echo ""
    echo "=== BESCHIKBARE LOGS ==="
    ls -la "$LOG_DIR"/*.log 2>/dev/null || echo "Geen logs gevonden"
    
    echo ""
    echo "Welke log wil je zien?"
    echo "  1) ollama.log"
    echo "  2) embedding_8000.log"
    echo "  3) analyzer_9100.log"
    echo "  4) reranker_9200.log"
    echo "  5) datafactory_9000.log"
    echo "  0) Terug"
    
    read -r choice
    case $choice in
        1) tail -100 "$LOG_DIR/ollama.log" 2>/dev/null || echo "Niet gevonden" ;;
        2) tail -100 "$LOG_DIR/embedding_8000.log" 2>/dev/null || echo "Niet gevonden" ;;
        3) tail -100 "$LOG_DIR/analyzer_9100.log" 2>/dev/null || echo "Niet gevonden" ;;
        4) tail -100 "$LOG_DIR/reranker_9200.log" 2>/dev/null || echo "Niet gevonden" ;;
        5) tail -100 "$LOG_DIR/datafactory_9000.log" 2>/dev/null || echo "Niet gevonden" ;;
        *) ;;
    esac
}

# Main menu
show_menu() {
    echo ""
    echo "========================================"
    echo "  DEBUG PIPELINE - Stap voor stap"
    echo "========================================"
    echo ""
    echo "  0) Status check (alle services)"
    echo "  ─────────────────────────────────"
    echo "  1) Start Ollama (LLM backend)"
    echo "  2) Start Embedding Service (:8000)"
    echo "  3) Start Doc Analyzer (:9100)"
    echo "  4) Start Reranker (:9200)"
    echo "  5) Start DataFactory (:9000)"
    echo "  ─────────────────────────────────"
    echo "  6) TEST: Document Analyse (70B)"
    echo "  7) TEST: Ingest (chunk + embed)"
    echo "  8) TEST: Search (met rerank)"
    echo "  ─────────────────────────────────"
    echo "  L) Bekijk logs"
    echo "  S) Stop alle services"
    echo "  G) GPU status"
    echo "  Q) Quit"
    echo ""
    echo -n "Keuze: "
}

# Main
main() {
    # Als argument gegeven, voer die stap direct uit
    if [ $# -gt 0 ]; then
        case $1 in
            0) step_status ;;
            1) step1_ollama ;;
            2) step2_embedding ;;
            3) step3_analyzer ;;
            4) step4_reranker ;;
            5) step5_datafactory ;;
            6) step6_test_analyze ;;
            7) step7_test_ingest ;;
            8) step8_test_search ;;
            stop) stop_all ;;
            *) echo "Onbekende stap: $1" ;;
        esac
        exit 0
    fi
    
    # Interactief menu
    while true; do
        show_menu
        read -r choice
        
        case $choice in
            0) step_status ;;
            1) step1_ollama ;;
            2) step2_embedding ;;
            3) step3_analyzer ;;
            4) step4_reranker ;;
            5) step5_datafactory ;;
            6) step6_test_analyze ;;
            7) step7_test_ingest ;;
            8) step8_test_search ;;
            [Ll]) show_logs ;;
            [Ss]) stop_all ;;
            [Gg]) show_gpu_status ;;
            [Qq]) echo "Bye!"; exit 0 ;;
            *) echo_warn "Ongeldige keuze" ;;
        esac
    done
}

main "$@"
