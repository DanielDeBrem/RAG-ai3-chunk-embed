#!/usr/bin/env bash
#
# Test script voor grote PDF ingest via AI-3 DataFactory
# 
# Dit test de fix voor HTTP connection abort tijdens lange processing
# van grote PDFs (>25MB).
#
# Usage:
#   bash test_large_pdf_ingest.sh
#

set -euo pipefail

# Kleuren
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_status() { echo -e "${BLUE}[TEST]${NC} $1"; }
echo_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
echo_err() { echo -e "${RED}[FAIL]${NC} $1"; }
echo_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# Config
AI3_DATAFACTORY_URL="http://10.0.1.44:9000"
TEST_PDF="data/20251224 Taxatierapport Camping de Brem 2025.pdf"
PROJECT_ID="test_large_pdf"
DOCUMENT_TYPE="jaarrekening"
DOC_ID="test_taxatierapport_$(date +%s)"
TIMEOUT=3600  # 1 uur, zoals AI-4 gebruikt

echo "========================================="
echo "  Test: Grote PDF Ingest (Connection Fix)"
echo "========================================="
echo "DataFactory URL: $AI3_DATAFACTORY_URL"
echo "Test PDF: $TEST_PDF"
echo "Timeout: ${TIMEOUT}s (1 uur)"
echo ""

# Check of test PDF bestaat
if [ ! -f "$TEST_PDF" ]; then
  echo_err "Test PDF niet gevonden: $TEST_PDF"
  exit 1
fi

# Check PDF grootte
PDF_SIZE=$(du -h "$TEST_PDF" | cut -f1)
PDF_SIZE_BYTES=$(stat -c%s "$TEST_PDF" 2>/dev/null || stat -f%z "$TEST_PDF" 2>/dev/null || echo "0")
echo_status "PDF grootte: $PDF_SIZE (${PDF_SIZE_BYTES} bytes)"

if [ "$PDF_SIZE_BYTES" -lt 10000000 ]; then
  echo_warn "PDF is klein (<10MB), mogelijk geen goede test voor connection timeout"
fi

# Check of DataFactory bereikbaar is
echo ""
echo_status "Checken of DataFactory bereikbaar is..."
if ! curl -s --max-time 5 "${AI3_DATAFACTORY_URL}/health" > /dev/null 2>&1; then
  echo_err "DataFactory niet bereikbaar op ${AI3_DATAFACTORY_URL}"
  echo "Start eerst de services met: bash start_AI3_services.sh"
  exit 1
fi
echo_ok "DataFactory is bereikbaar"

# Extract text from PDF (AI-4 doet dit eerst via analyzer)
echo ""
echo_status "Extracting text from PDF..."
TEXT=$(python3 -c "
from pypdf import PdfReader
import sys
reader = PdfReader('$TEST_PDF')
pages = []
for i, page in enumerate(reader.pages):
    txt = page.extract_text() or ''
    pages.append(f'[PAGE {i+1}]\\n{txt}')
print('\\n\\n'.join(pages))
" 2>/dev/null)

TEXT_LENGTH=${#TEXT}
echo_ok "Extracted ${TEXT_LENGTH} characters"

if [ "$TEXT_LENGTH" -lt 1000 ]; then
  echo_err "Text too short (${TEXT_LENGTH} chars), PDF extraction may have failed"
  exit 1
fi

# Prepare JSON payload
echo ""
echo_status "Preparing ingest request..."

# Create temp file for JSON (escape text properly)
TEMP_JSON=$(mktemp)
cat > "$TEMP_JSON" <<EOF
{
  "project_id": "$PROJECT_ID",
  "document_type": "$DOCUMENT_TYPE",
  "doc_id": "$DOC_ID",
  "text": $(echo "$TEXT" | jq -Rs .),
  "chunk_strategy": "page_plus_table_aware",
  "chunk_overlap": 200,
  "metadata": {
    "filename": "$(basename "$TEST_PDF")",
    "test_run": true,
    "test_timestamp": "$(date -Iseconds)"
  }
}
EOF

PAYLOAD_SIZE=$(du -h "$TEMP_JSON" | cut -f1)
echo_ok "Payload size: $PAYLOAD_SIZE"

# Send ingest request met lange timeout
echo ""
echo_status "Sending ingest request to DataFactory..."
echo_status "Timeout: ${TIMEOUT}s (monitoring for connection abort)"
echo_warn "Dit kan lang duren voor grote PDFs (5-30 minuten)..."
echo ""

START_TIME=$(date +%s)

# Run curl met verbose output voor debugging
RESPONSE=$(curl -X POST "${AI3_DATAFACTORY_URL}/v1/rag/ingest/text" \
  -H "Content-Type: application/json" \
  --data @"$TEMP_JSON" \
  --max-time "$TIMEOUT" \
  --connect-timeout 30 \
  -w "\nHTTP_CODE:%{http_code}\nTIME_TOTAL:%{time_total}\n" \
  -v 2>&1)

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Cleanup temp file
rm -f "$TEMP_JSON"

# Parse response
HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d: -f2 | tr -d ' ')
TIME_TOTAL=$(echo "$RESPONSE" | grep "TIME_TOTAL:" | cut -d: -f2 | tr -d ' ')

echo ""
echo "========================================="
echo "  Test Results"
echo "========================================="
echo "Duration: ${DURATION}s (${TIME_TOTAL}s actual)"
echo "HTTP Code: ${HTTP_CODE:-FAILED}"
echo ""

# Check for connection errors
if echo "$RESPONSE" | grep -qi "connection.*abort\|remote.*disconnect\|broken.*pipe"; then
  echo_err "CONNECTION ABORT DETECTED!"
  echo "Response indicates connection was closed prematurely:"
  echo "$RESPONSE" | grep -i "connection\|disconnect\|pipe" | head -5
  echo ""
  echo "This suggests the uvicorn timeout fix is not working."
  echo "Check logs: tail -f logs/datafactory_9000.log"
  exit 1
fi

# Check HTTP response
if [ -z "$HTTP_CODE" ]; then
  echo_err "No HTTP response received"
  echo "Full response:"
  echo "$RESPONSE"
  exit 1
fi

if [ "$HTTP_CODE" = "200" ]; then
  echo_ok "HTTP 200 - Request successful!"
  
  # Parse JSON response
  JSON_RESPONSE=$(echo "$RESPONSE" | grep -v "HTTP_CODE:\|TIME_TOTAL:\|^\*\|^<\|^>" | grep "chunks_added" || echo "{}")
  CHUNKS_ADDED=$(echo "$JSON_RESPONSE" | jq -r '.chunks_added // 0' 2>/dev/null || echo "0")
  
  echo ""
  echo "Response:"
  echo "$JSON_RESPONSE" | jq . 2>/dev/null || echo "$JSON_RESPONSE"
  echo ""
  
  if [ "$CHUNKS_ADDED" -gt 0 ]; then
    echo_ok "SUCCESS: ${CHUNKS_ADDED} chunks stored"
    echo ""
    echo "Test PASSED ✓"
    echo "Large PDF was processed without connection abort!"
  else
    echo_warn "Request succeeded but no chunks were stored"
    echo "This may indicate a deduplication or empty content issue"
  fi
  
elif [ "$HTTP_CODE" = "504" ] || [ "$HTTP_CODE" = "408" ]; then
  echo_err "TIMEOUT ERROR (HTTP ${HTTP_CODE})"
  echo "The request took longer than ${TIMEOUT}s"
  echo "Consider increasing timeout or optimizing processing"
  exit 1
  
elif [ "$HTTP_CODE" = "500" ]; then
  echo_err "SERVER ERROR (HTTP 500)"
  echo "Check logs for details: tail -f logs/datafactory_9000.log"
  exit 1
  
else
  echo_err "Unexpected HTTP code: ${HTTP_CODE}"
  echo "Full response:"
  echo "$RESPONSE"
  exit 1
fi

# Check logs for errors
echo ""
echo_status "Checking recent logs for errors..."
if tail -100 logs/datafactory_9000.log 2>/dev/null | grep -i "error\|exception\|failed" | tail -5 | grep -v "INFO" ; then
  echo_warn "Errors found in logs (see above)"
else
  echo_ok "No recent errors in logs"
fi

echo ""
echo "========================================="
echo "Test completed successfully!"
echo "Duration: ${DURATION}s"
echo "========================================="
