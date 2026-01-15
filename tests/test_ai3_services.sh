#!/usr/bin/env bash
#
# AI-3 Services Test Script
# Test alle services lokaal voordat AI-4 wordt aangesloten
#

set -euo pipefail

# Configuratie
AI3_HOST="${AI3_HOST:-10.0.1.44}"
EMBEDDING_PORT=8000
DATAFACTORY_PORT=9000
ANALYZER_PORT=9100
RERANKER_PORT=9200

# Kleuren
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
TESTS_PASSED=0
TESTS_FAILED=0

# Helper functies
log_test() {
    echo -e "\n${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}TEST: $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
}

log_pass() {
    echo -e "${GREEN}✅ PASS: $1${NC}"
    ((TESTS_PASSED++))
}

log_fail() {
    echo -e "${RED}❌ FAIL: $1${NC}"
    ((TESTS_FAILED++))
}

log_info() {
    echo -e "${YELLOW}ℹ️  $1${NC}"
}

# Test functie met timeout
test_endpoint() {
    local name="$1"
    local method="$2"
    local url="$3"
    local data="${4:-}"
    local expected_field="${5:-status}"
    
    log_info "Testing: $name"
    log_info "URL: $url"
    
    local start_time=$(date +%s%N)
    
    if [ "$method" == "GET" ]; then
        response=$(curl -s --connect-timeout 5 -w "\n%{http_code}" "$url" 2>/dev/null) || {
            log_fail "$name - Connection failed"
            return 1
        }
    else
        response=$(curl -s --connect-timeout 10 -X POST -H "Content-Type: application/json" -d "$data" -w "\n%{http_code}" "$url" 2>/dev/null) || {
            log_fail "$name - Connection failed"
            return 1
        }
    fi
    
    local end_time=$(date +%s%N)
    local duration=$(( (end_time - start_time) / 1000000 ))
    
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        if echo "$body" | jq -e ".$expected_field" > /dev/null 2>&1; then
            log_pass "$name (${duration}ms)"
            echo -e "Response: $body" | head -c 500
            echo ""
            return 0
        else
            log_fail "$name - Missing expected field: $expected_field"
            echo -e "Response: $body" | head -c 500
            echo ""
            return 1
        fi
    else
        log_fail "$name - HTTP $http_code"
        echo -e "Response: $body" | head -c 500
        echo ""
        return 1
    fi
}

echo -e "\n${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           AI-3 Services Integration Test Suite               ║${NC}"
echo -e "${GREEN}║                  Host: $AI3_HOST                            ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"

# =============================================================================
# TEST 1: Health Checks
# =============================================================================
log_test "1. Health Checks - Alle Services"

test_endpoint "Embedding Service :$EMBEDDING_PORT" "GET" "http://$AI3_HOST:$EMBEDDING_PORT/health" "" "status" || true
test_endpoint "DataFactory :$DATAFACTORY_PORT" "GET" "http://$AI3_HOST:$DATAFACTORY_PORT/health" "" "status" || true
test_endpoint "Document Analyzer :$ANALYZER_PORT" "GET" "http://$AI3_HOST:$ANALYZER_PORT/health" "" "status" || true
test_endpoint "Reranker :$RERANKER_PORT" "GET" "http://$AI3_HOST:$RERANKER_PORT/health" "" "status" || true

# =============================================================================
# TEST 2: Embedding Service
# =============================================================================
log_test "2. Embedding Service - Tekst Embedden"

EMBED_DATA='{
    "texts": ["Dit is een test tekst voor embedding.", "Dit is een tweede test."]
}'

test_endpoint "Embed 2 teksten" "POST" "http://$AI3_HOST:$EMBEDDING_PORT/embed" "$EMBED_DATA" "embeddings" || true

# =============================================================================
# TEST 3: Document Analyzer
# =============================================================================
log_test "3. Document Analyzer - LLM Enrichment"

ANALYZE_DATA='{
    "document": "Jaarrekening 2024\n\nDaSol B.V.\n\nBalans per 31 december 2024\n\nActiva:\n- Vaste activa: €100.000\n- Vlottende activa: €50.000\n\nPassiva:\n- Eigen vermogen: €80.000\n- Vreemd vermogen: €70.000\n\nWinst- en verliesrekening:\nOmzet: €500.000\nKosten: €400.000\nResultaat: €100.000",
    "filename": "jaarrekening_2024.pdf",
    "mime_type": "application/pdf"
}'

log_info "Let op: Analyzer test kan 30-60 sec duren (Llama 70B)"
test_endpoint "Analyze jaarrekening" "POST" "http://$AI3_HOST:$ANALYZER_PORT/analyze" "$ANALYZE_DATA" "analysis" || true

# =============================================================================
# TEST 4: DataFactory Ingest - Alle Chunk Strategies
# =============================================================================
log_test "4. DataFactory Ingest - Chunk Strategies"

# Test 4a: Default strategy
INGEST_DEFAULT='{
    "project_id": "test-project",
    "document_type": "generic",
    "doc_id": "test-default-1",
    "text": "Dit is een eerste paragraaf met wat test content voor de default chunking strategy.\n\nDit is een tweede paragraaf die ook getest moet worden.\n\nEn een derde paragraaf voor de volledigheid.",
    "chunk_strategy": "default",
    "metadata": {"test": "default_strategy"}
}'
test_endpoint "Ingest: default strategy" "POST" "http://$AI3_HOST:$DATAFACTORY_PORT/v1/rag/ingest/text" "$INGEST_DEFAULT" "chunks_added" || true

# Test 4b: Page aware strategy
INGEST_PAGE='{
    "project_id": "test-project",
    "document_type": "jaarrekening",
    "doc_id": "test-page-1",
    "text": "[PAGE 1]\nJaarrekening 2024\n\nDit is de eerste pagina met introductie.\n\n[PAGE 2]\nBalans per 31 december 2024\n\nActiva:\n- Vaste activa: €100.000\n\n[PAGE 3]\nWinst- en verliesrekening\n\nOmzet: €500.000",
    "chunk_strategy": "page_plus_table_aware",
    "metadata": {"test": "page_strategy"}
}'
test_endpoint "Ingest: page_plus_table_aware" "POST" "http://$AI3_HOST:$DATAFACTORY_PORT/v1/rag/ingest/text" "$INGEST_PAGE" "chunks_added" || true

# Test 4c: Semantic sections
INGEST_SEMANTIC='{
    "project_id": "test-project",
    "document_type": "offertes",
    "doc_id": "test-semantic-1",
    "text": "# Offerte\n\nBeste klant,\n\nHierbij onze offerte.\n\n## Producten\n\n- Product A: €100\n- Product B: €200\n\n## Voorwaarden\n\nLevering binnen 5 werkdagen.",
    "chunk_strategy": "semantic_sections",
    "metadata": {"test": "semantic_strategy"}
}'
test_endpoint "Ingest: semantic_sections" "POST" "http://$AI3_HOST:$DATAFACTORY_PORT/v1/rag/ingest/text" "$INGEST_SEMANTIC" "chunks_added" || true

# Test 4d: Conversation turns
INGEST_CONV='{
    "project_id": "test-project",
    "document_type": "coaching_chat",
    "doc_id": "test-conv-1",
    "text": "Coach: Welkom bij deze sessie. Hoe gaat het met je?\n\nClient: Het gaat redelijk, ik heb wat stress op werk.\n\nCoach: Vertel me daar meer over.\n\nClient: Mijn leidinggevende stelt hoge eisen en ik heb moeite om alles bij te houden.",
    "chunk_strategy": "conversation_turns",
    "metadata": {"test": "conversation_strategy"}
}'
test_endpoint "Ingest: conversation_turns" "POST" "http://$AI3_HOST:$DATAFACTORY_PORT/v1/rag/ingest/text" "$INGEST_CONV" "chunks_added" || true

# Test 4e: Table aware
INGEST_TABLE='{
    "project_id": "test-project",
    "document_type": "generic",
    "doc_id": "test-table-1",
    "text": "Financieel overzicht\n\nHieronder de cijfers:\n\n| Jaar | Omzet | Winst |\n|------|-------|-------|\n| 2022 | 100k  | 10k   |\n| 2023 | 150k  | 20k   |\n| 2024 | 200k  | 30k   |\n\nConclusions volgen hieronder.",
    "chunk_strategy": "table_aware",
    "metadata": {"test": "table_strategy"}
}'
test_endpoint "Ingest: table_aware" "POST" "http://$AI3_HOST:$DATAFACTORY_PORT/v1/rag/ingest/text" "$INGEST_TABLE" "chunks_added" || true

# Test 4f: Auto strategy (geen chunk_strategy meegeven)
INGEST_AUTO='{
    "project_id": "test-project",
    "document_type": "jaarrekening",
    "doc_id": "test-auto-1",
    "text": "[PAGE 1]\nJaarrekening automatische strategie selectie test.\n\n[PAGE 2]\nDeze test zou automatisch page_plus_table_aware moeten kiezen.",
    "metadata": {"test": "auto_strategy"}
}'
test_endpoint "Ingest: auto strategy (geen chunk_strategy)" "POST" "http://$AI3_HOST:$DATAFACTORY_PORT/v1/rag/ingest/text" "$INGEST_AUTO" "chunks_added" || true

# =============================================================================
# TEST 5: Search + Reranking
# =============================================================================
log_test "5. DataFactory Search + Reranking"

SEARCH_DATA='{
    "project_id": "test-project",
    "document_type": "jaarrekening",
    "question": "Wat is de omzet?",
    "top_k": 3
}'
test_endpoint "Search jaarrekening" "POST" "http://$AI3_HOST:$DATAFACTORY_PORT/v1/rag/search" "$SEARCH_DATA" "chunks" || true

SEARCH_CONV='{
    "project_id": "test-project",
    "document_type": "coaching_chat",
    "question": "Wat is het probleem van de client?",
    "top_k": 3
}'
test_endpoint "Search coaching chat" "POST" "http://$AI3_HOST:$DATAFACTORY_PORT/v1/rag/search" "$SEARCH_CONV" "chunks" || true

# =============================================================================
# TEST 6: Reranker Direct Test
# =============================================================================
log_test "6. Reranker Service - Direct Test"

RERANK_DATA='{
    "query": "Wat is de omzet van het bedrijf?",
    "items": [
        {"id": "1", "text": "De omzet in 2024 was €500.000", "metadata": {}},
        {"id": "2", "text": "Het weer was mooi vandaag", "metadata": {}},
        {"id": "3", "text": "De jaaromzet steeg naar €500k", "metadata": {}},
        {"id": "4", "text": "Balans per 31 december", "metadata": {}}
    ],
    "top_k": 2
}'
test_endpoint "Rerank 4 items naar top 2" "POST" "http://$AI3_HOST:$RERANKER_PORT/rerank" "$RERANK_DATA" "items" || true

# =============================================================================
# TEST 7: End-to-End Flow
# =============================================================================
log_test "7. End-to-End Flow Test"

log_info "Stap 1: Analyze document"
E2E_ANALYZE='{
    "document": "Offerte voor webontwikkeling\n\nPrijs: €5.000\n\nLevering: 4 weken\n\nInclusief:\n- Design\n- Development\n- Testing",
    "filename": "offerte_web.pdf"
}'

analyze_result=$(curl -s --connect-timeout 30 -X POST -H "Content-Type: application/json" \
    -d "$E2E_ANALYZE" "http://$AI3_HOST:$ANALYZER_PORT/analyze" 2>/dev/null) || true

if [ -n "$analyze_result" ]; then
    suggested_strategy=$(echo "$analyze_result" | jq -r '.analysis.suggested_chunk_strategy // "default"' 2>/dev/null) || suggested_strategy="default"
    log_info "Analyzer suggested strategy: $suggested_strategy"
    log_pass "E2E Stap 1: Analyze"
else
    log_fail "E2E Stap 1: Analyze"
    suggested_strategy="semantic_sections"
fi

log_info "Stap 2: Ingest met suggested strategy ($suggested_strategy)"
E2E_INGEST=$(cat <<EOF
{
    "project_id": "e2e-test",
    "document_type": "offertes",
    "doc_id": "e2e-offerte-1",
    "text": "Offerte voor webontwikkeling\n\nPrijs: €5.000\n\nLevering: 4 weken\n\nInclusief:\n- Design\n- Development\n- Testing",
    "chunk_strategy": "$suggested_strategy",
    "metadata": {"source": "e2e_test"}
}
EOF
)

test_endpoint "E2E Stap 2: Ingest" "POST" "http://$AI3_HOST:$DATAFACTORY_PORT/v1/rag/ingest/text" "$E2E_INGEST" "chunks_added" || true

log_info "Stap 3: Search in ingested document"
E2E_SEARCH='{
    "project_id": "e2e-test",
    "document_type": "offertes",
    "question": "Wat is de prijs?",
    "top_k": 2
}'
test_endpoint "E2E Stap 3: Search" "POST" "http://$AI3_HOST:$DATAFACTORY_PORT/v1/rag/search" "$E2E_SEARCH" "chunks" || true

# =============================================================================
# RESULTATEN
# =============================================================================
echo -e "\n${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                      TEST RESULTATEN                          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"

echo -e "\n${GREEN}✅ Tests geslaagd: $TESTS_PASSED${NC}"
echo -e "${RED}❌ Tests gefaald: $TESTS_FAILED${NC}"

TOTAL=$((TESTS_PASSED + TESTS_FAILED))
if [ $TOTAL -gt 0 ]; then
    PERCENTAGE=$((TESTS_PASSED * 100 / TOTAL))
    echo -e "\n📊 Success rate: ${PERCENTAGE}%"
fi

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "\n${GREEN}🎉 Alle tests geslaagd! Klaar voor AI-4 integratie.${NC}"
    exit 0
else
    echo -e "\n${YELLOW}⚠️  Sommige tests gefaald. Check de logs hierboven.${NC}"
    exit 1
fi
