#!/bin/bash
# ============================================
# AI-3 Complete Test Suite
# Tests all endpoints with proper payloads
# ============================================

set +e  # Don't exit on error, we want to see all test results

# Kleuren
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuratie
DATAFACTORY_PORT="${DATAFACTORY_PORT:-9000}"
DOC_ANALYZER_PORT="${DOC_ANALYZER_PORT:-9100}"
RERANKER_PORT="${RERANKER_PORT:-9200}"

DATAFACTORY_URL="http://localhost:$DATAFACTORY_PORT"
DOC_ANALYZER_URL="http://localhost:$DOC_ANALYZER_PORT"
RERANKER_URL="http://localhost:$RERANKER_PORT"

# Test counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

echo "=========================================="
echo "AI-3 Complete Test Suite"
echo "=========================================="
echo ""

# Helper functie voor test uitvoeren
run_test() {
    local test_name="$1"
    local curl_cmd="$2"
    local expected_status="${3:-200}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    echo -e "${BLUE}[TEST $TOTAL_TESTS]${NC} $test_name"
    echo "  Command: $curl_cmd"
    
    # Voer curl uit en capture status
    response=$(eval "$curl_cmd" 2>&1)
    status=$?
    
    # Check of curl succesvol was
    if [ $status -eq 0 ]; then
        # Check of response JSON bevat
        if echo "$response" | jq . > /dev/null 2>&1; then
            echo -e "${GREEN}  ✓ PASSED${NC}"
            echo "  Response: $(echo "$response" | jq -c . 2>/dev/null | head -c 100)..."
            PASSED_TESTS=$((PASSED_TESTS + 1))
        else
            echo -e "${RED}  ✗ FAILED${NC} - Invalid JSON response"
            echo "  Response: $response"
            FAILED_TESTS=$((FAILED_TESTS + 1))
        fi
    else
        echo -e "${RED}  ✗ FAILED${NC} - curl error (status: $status)"
        echo "  Error: $response"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    echo ""
}

# ============================================
# 1. Health Checks
# ============================================
echo "=========================================="
echo "1. Health Checks"
echo "=========================================="
echo ""

run_test "DataFactory Health" \
    "curl -s -X GET $DATAFACTORY_URL/health"

run_test "Doc Analyzer Health" \
    "curl -s -X GET $DOC_ANALYZER_URL/health"

run_test "Reranker Health" \
    "curl -s -X GET $RERANKER_URL/health"

# ============================================
# 2. Doc Analyzer Tests
# ============================================
echo "=========================================="
echo "2. Doc Analyzer Tests"
echo "=========================================="
echo ""

# Test document met financiële content
DOC_TEXT="Dit is een jaarrekening voor 2024. De balans toont activa van EUR 1.000.000 en passiva van EUR 800.000. De winst- en verliesrekening toont een nettowinst van EUR 200.000. Belangrijke bedrijven: Camping de Brem BV, Taxatierapport NV."

run_test "Doc Analyzer - Analyze Document" \
    "curl -s -X POST $DOC_ANALYZER_URL/analyze \
    -H 'Content-Type: application/json' \
    -d '{
        \"document\": \"$DOC_TEXT\",
        \"filename\": \"jaarrekening_2024.pdf\",
        \"mime_type\": \"application/pdf\"
    }'"

run_test "Doc Analyzer - Async Analyze" \
    "curl -s -X POST $DOC_ANALYZER_URL/analyze/async \
    -H 'Content-Type: application/json' \
    -d '{
        \"document\": \"Test document voor async analyse\",
        \"filename\": \"test_async.txt\",
        \"mime_type\": \"text/plain\"
    }'"

# ============================================
# 3. DataFactory Ingest Tests
# ============================================
echo "=========================================="
echo "3. DataFactory Ingest Tests"
echo "=========================================="
echo ""

# Test ingest with different chunk strategies
run_test "DataFactory - Ingest Text (default strategy)" \
    "curl -s -X POST $DATAFACTORY_URL/v1/rag/ingest/text \
    -H 'Content-Type: application/json' \
    -d '{
        \"project_id\": \"test_project\",
        \"document_type\": \"generic\",
        \"doc_id\": \"test_doc_001\",
        \"text\": \"Dit is een test document voor de ingestion pipeline. Het bevat meerdere paragrafen. Eerste paragraaf hier. Tweede paragraaf daar. Derde paragraaf ergens anders.\",
        \"chunk_strategy\": \"default\",
        \"chunk_overlap\": 0,
        \"metadata\": {
            \"filename\": \"test.txt\",
            \"source\": \"test_suite\"
        }
    }'"

run_test "DataFactory - Ingest Text (table_aware strategy)" \
    "curl -s -X POST $DATAFACTORY_URL/v1/rag/ingest/text \
    -H 'Content-Type: application/json' \
    -d '{
        \"project_id\": \"test_project\",
        \"document_type\": \"jaarrekening\",
        \"doc_id\": \"test_doc_002\",
        \"text\": \"Balans 2024\n| Activa | EUR |\n| Kas | 100.000 |\n| Bank | 200.000 |\n\nPassiva\n| Schulden | EUR |\n| Leveranciers | 50.000 |\",
        \"chunk_strategy\": \"table_aware\",
        \"chunk_overlap\": 50,
        \"metadata\": {
            \"filename\": \"balans.txt\",
            \"year\": 2024
        }
    }'"

# ============================================
# 4. DataFactory Search Tests
# ============================================
echo "=========================================="
echo "4. DataFactory Search Tests"
echo "=========================================="
echo ""

run_test "DataFactory - Search Query" \
    "curl -s -X POST $DATAFACTORY_URL/v1/rag/search \
    -H 'Content-Type: application/json' \
    -d '{
        \"project_id\": \"test_project\",
        \"document_type\": \"generic\",
        \"question\": \"Wat zijn de paragrafen?\",
        \"top_k\": 3
    }'"

run_test "DataFactory - Search with Reranking" \
    "curl -s -X POST $DATAFACTORY_URL/v1/rag/search \
    -H 'Content-Type: application/json' \
    -d '{
        \"project_id\": \"test_project\",
        \"document_type\": \"jaarrekening\",
        \"question\": \"Hoeveel geld in de kas?\",
        \"top_k\": 5
    }'"

# ============================================
# 5. Reranker Tests
# ============================================
echo "=========================================="
echo "5. Reranker Tests"
echo "=========================================="
echo ""

run_test "Reranker - Rerank Items" \
    "curl -s -X POST $RERANKER_URL/rerank \
    -H 'Content-Type: application/json' \
    -d '{
        \"query\": \"financiële resultaten 2024\",
        \"items\": [
            {
                \"id\": \"chunk_1\",
                \"text\": \"De winst in 2024 was EUR 200.000\",
                \"metadata\": {}
            },
            {
                \"id\": \"chunk_2\",
                \"text\": \"Het weer was mooi vandaag\",
                \"metadata\": {}
            },
            {
                \"id\": \"chunk_3\",
                \"text\": \"Balans 2024: activa EUR 1M\",
                \"metadata\": {}
            }
        ],
        \"top_k\": 2
    }'"

# ============================================
# 6. GPU Status Tests
# ============================================
echo "=========================================="
echo "6. GPU Status Tests"
echo "=========================================="
echo ""

run_test "DataFactory - GPU Status" \
    "curl -s -X GET $DATAFACTORY_URL/gpu/status"

run_test "Doc Analyzer - GPU Status" \
    "curl -s -X GET $DOC_ANALYZER_URL/gpu/status"

run_test "DataFactory - Embedder Status" \
    "curl -s -X GET $DATAFACTORY_URL/embedder/status"

# ============================================
# 7. Integration Tests (AI-4 Simulation)
# ============================================
echo "=========================================="
echo "7. Integration Tests"
echo "=========================================="
echo ""

# Test volledige flow: analyze → ingest → search
echo -e "${YELLOW}Running full integration test...${NC}"
echo ""

# Step 1: Analyze
echo "Step 1: Analyzing document..."
ANALYZE_RESPONSE=$(curl -s -X POST $DOC_ANALYZER_URL/analyze \
    -H 'Content-Type: application/json' \
    -d '{
        "document": "Taxatierapport Camping de Brem. Waarde vastgesteld op EUR 2.500.000. Locatie: Renesse, Zuid-Holland. Oppervlakte: 5 hectare. Bezetting: 80% gemiddeld.",
        "filename": "taxatierapport.pdf",
        "mime_type": "application/pdf"
    }')

if echo "$ANALYZE_RESPONSE" | jq -e '.analysis.document_type' > /dev/null 2>&1; then
    DOC_TYPE=$(echo "$ANALYZE_RESPONSE" | jq -r '.analysis.document_type')
    CHUNK_STRATEGY=$(echo "$ANALYZE_RESPONSE" | jq -r '.analysis.suggested_chunk_strategy')
    echo -e "${GREEN}  ✓ Analysis complete: type=$DOC_TYPE, strategy=$CHUNK_STRATEGY${NC}"
else
    echo -e "${RED}  ✗ Analysis failed${NC}"
    DOC_TYPE="generic"
    CHUNK_STRATEGY="default"
fi
echo ""

# Step 2: Ingest
echo "Step 2: Ingesting document..."
INGEST_RESPONSE=$(curl -s -X POST $DATAFACTORY_URL/v1/rag/ingest/text \
    -H 'Content-Type: application/json' \
    -d "{
        \"project_id\": \"integration_test\",
        \"document_type\": \"$DOC_TYPE\",
        \"doc_id\": \"taxatierapport_001\",
        \"text\": \"Taxatierapport Camping de Brem. Waarde vastgesteld op EUR 2.500.000. Locatie: Renesse, Zuid-Holland. Oppervlakte: 5 hectare. Bezetting: 80% gemiddeld. De camping beschikt over 150 standplaatsen en moderne sanitaire voorzieningen.\",
        \"chunk_strategy\": \"$CHUNK_STRATEGY\",
        \"metadata\": {
            \"filename\": \"taxatierapport.pdf\",
            \"test_type\": \"integration\"
        }
    }")

if echo "$INGEST_RESPONSE" | jq -e '.chunks_added' > /dev/null 2>&1; then
    CHUNKS_ADDED=$(echo "$INGEST_RESPONSE" | jq -r '.chunks_added')
    echo -e "${GREEN}  ✓ Ingest complete: $CHUNKS_ADDED chunks added${NC}"
else
    echo -e "${RED}  ✗ Ingest failed${NC}"
    CHUNKS_ADDED=0
fi
echo ""

# Step 3: Search
if [ "$CHUNKS_ADDED" -gt 0 ]; then
    echo "Step 3: Searching ingested content..."
    SEARCH_RESPONSE=$(curl -s -X POST $DATAFACTORY_URL/v1/rag/search \
        -H 'Content-Type: application/json' \
        -d "{
            \"project_id\": \"integration_test\",
            \"document_type\": \"$DOC_TYPE\",
            \"question\": \"Wat is de waarde van de camping?\",
            \"top_k\": 3
        }")
    
    if echo "$SEARCH_RESPONSE" | jq -e '.chunks[0]' > /dev/null 2>&1; then
        RESULT_COUNT=$(echo "$SEARCH_RESPONSE" | jq -r '.chunks | length')
        TOP_SCORE=$(echo "$SEARCH_RESPONSE" | jq -r '.chunks[0].score')
        echo -e "${GREEN}  ✓ Search complete: $RESULT_COUNT results, top score=$TOP_SCORE${NC}"
        echo "  Top result: $(echo "$SEARCH_RESPONSE" | jq -r '.chunks[0].text' | head -c 80)..."
    else
        echo -e "${RED}  ✗ Search failed or no results${NC}"
    fi
else
    echo -e "${YELLOW}  ⚠ Skipping search (no chunks ingested)${NC}"
fi
echo ""

# ============================================
# Test Summary
# ============================================
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo ""
echo "Total tests:  $TOTAL_TESTS"
echo -e "Passed:       ${GREEN}$PASSED_TESTS${NC}"
echo -e "Failed:       ${RED}$FAILED_TESTS${NC}"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}=========================================="
    echo "ALL TESTS PASSED! ✓"
    echo -e "==========================================${NC}"
    exit 0
else
    echo -e "${RED}=========================================="
    echo "SOME TESTS FAILED! ✗"
    echo -e "==========================================${NC}"
    echo ""
    echo "Check service logs for details:"
    echo "  tail -f logs/datafactory.log"
    echo "  tail -f logs/doc_analyzer.log"
    echo "  tail -f logs/reranker.log"
    exit 1
fi
