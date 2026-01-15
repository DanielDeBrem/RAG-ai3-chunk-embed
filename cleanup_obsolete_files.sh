#!/bin/bash
# Cleanup Script voor Obsolete Files
# Gegenereerd: 14 januari 2026
# 
# BELANGRIJK: Review deze lijst voordat je het uitvoert!

set -e

echo "=========================================="
echo "AI-3 Project Cleanup"
echo "=========================================="
echo ""

# Kleuren
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Teller
REMOVED_COUNT=0

# ============================================
# FASE 1: ZEKER VERWIJDEREN
# ============================================
echo -e "${GREEN}FASE 1: Backup files & Fix scripts (ZEKER)${NC}"
echo ""

# 1. Python backup files
echo "1. Removing Python backup files..."
for file in \
    analyzer_schemas.py.bak_20260103_021817 \
    app.py.backup_before_cleanup \
    app.py.backup_before_v2_integration_20260112_233941 \
    doc_analyzer_service.py.bak_20260103_021817 \
    doc_analyzer.py.bak_20260103_021523 \
    doc_analyzer.py.bak_20260103_021817
do
    if [ -f "$file" ]; then
        rm -v "$file"
        ((REMOVED_COUNT++))
    fi
done
echo ""

# 2. Backup directories
echo "2. Removing backup directories..."
for dir in \
    backup_20251231_190640 \
    backup_datafactory_20260103_082737 \
    backup_datafactory_20260103_100030 \
    backup_datafactory_20260103_100749 \
    backup_doc_type_20260103_082053 \
    backup_fix_ingest_20260103_093514 \
    backup_fix_ingest_lenient_20260103_094526 \
    backup_kw_20260103_081718
do
    if [ -d "$dir" ]; then
        echo "  Removing $dir/"
        rm -rf "$dir"
        ((REMOVED_COUNT++))
    fi
done
echo ""

# 3. Fix scripts
echo "3. Removing ad-hoc fix scripts..."
for file in \
    fix_ai3_analyzer_kw.sh \
    fix_ai3_analyzer_safe.sh \
    fix_ai3_datafactory.sh \
    fix_ai3_doc_type_kw.sh \
    fix_analyzer_stack.sh \
    fix_datafactory_422.sh \
    fix_doc_analyzer.sh \
    fix_ingest_422.sh \
    fix_ingest_lenient.sh \
    fix.sh \
    enable_multi_gpu_enrichment.sh \
    mk_datafactory_app.sh
do
    if [ -f "$file" ]; then
        rm -v "$file"
        ((REMOVED_COUNT++))
    fi
done
echo ""

# 4. Oude startup scripts (already removed)
echo "4. Checking oude startup scripts..."
for file in start_AI3_services_old_v1.sh
do
    if [ -f "$file" ]; then
        rm -v "$file"
        ((REMOVED_COUNT++))
    else
        echo "  $file already removed ✓"
    fi
done
echo ""

# 5. Test output files
echo "5. Removing test output files..."
for file in test_results_final.log test_results.log
do
    if [ -f "$file" ]; then
        rm -v "$file"
        ((REMOVED_COUNT++))
    fi
done
echo ""

# ============================================
# FASE 2: OUDE VERSIES (indien app_v1 niet actief)
# ============================================
echo -e "${YELLOW}FASE 2: Oude versies (alleen als app.py actief is)${NC}"
echo ""

# Check if app.py is de actieve versie
echo "Checking if app.py is active version..."
if grep -q "FastAPI" app.py && [ -f "app_v1.py" ]; then
    echo -e "${YELLOW}⚠️  VRAAG: Is app.py de actieve versie en app_v1.py obsolete?${NC}"
    echo "   Als JA: we kunnen app_v1.py, index_manager.py, job_queue.py, worker.py verwijderen"
    echo "   Als NEE: skip deze fase"
    echo ""
    echo "   Druk ENTER om deze fase OVER TE SLAAN"
    echo "   Type 'yes' om app_v1.py + dependencies te verwijderen"
    read -r CONFIRM
    
    if [ "$CONFIRM" = "yes" ]; then
        echo "Removing app_v1.py and its dependencies..."
        for file in app_v1.py index_manager.py job_queue.py worker.py test_persistence.py
        do
            if [ -f "$file" ]; then
                rm -v "$file"
                ((REMOVED_COUNT++))
            fi
        done
        echo ""
    else
        echo "Skipped app_v1.py removal"
        echo ""
    fi
else
    echo "app.py found, app_v1.py not found or already removed"
    echo ""
fi

# ============================================
# FASE 3: OUDE DOCUMENTATIE
# ============================================
echo -e "${YELLOW}FASE 3: Oude/Historische Documentatie${NC}"
echo ""

mkdir -p archive/old_docs

echo "Moving oude documentatie naar archive/old_docs/..."
for file in \
    BLUNDERS.md \
    CLEANUP_SUMMARY.md \
    CODE_CLEANUP_PLAN.md \
    CHUNKING_PROGRESS.md \
    DOC_ANALYZER_ANALYSIS.md \
    PIPELINE_GPU_ANALYSIS.md \
    PIPELINE_IMPROVEMENTS.md \
    SERVICE_STARTUP_FIX.md \
    STARTUP_STATUS_20260114.md \
    README_V1.md \
    CHANGELOG_V1.md
do
    if [ -f "$file" ]; then
        mv -v "$file" archive/old_docs/
        ((REMOVED_COUNT++))
    fi
done
echo ""

# ============================================
# FASE 4: gpu_phase_lock.py cleanup
# ============================================
echo -e "${YELLOW}FASE 4: gpu_phase_lock.py (DEPRECATED dummy)${NC}"
echo ""

echo "⚠️  gpu_phase_lock.py is DEPRECATED (no-op dummy)"
echo "   Maar nog geïmporteerd in: reranker.py, parallel_analyzer.py"
echo ""
echo "   Druk ENTER om dit OVER TE SLAAN"
echo "   Type 'yes' om gpu_phase_lock.py imports te verwijderen en file te deleten"
read -r CONFIRM

if [ "$CONFIRM" = "yes" ]; then
    echo "Removing gpu_phase_lock imports and file..."
    
    # Remove from reranker.py
    if [ -f "reranker.py" ]; then
        sed -i '/from gpu_phase_lock import gpu_exclusive_lock/d' reranker.py
        sed -i '/with gpu_exclusive_lock/d' reranker.py
        echo "  Updated reranker.py"
    fi
    
    # Remove from parallel_analyzer.py
    if [ -f "parallel_analyzer.py" ]; then
        sed -i '/from gpu_phase_lock import gpu_exclusive_lock/d' parallel_analyzer.py
        sed -i '/with gpu_exclusive_lock/d' parallel_analyzer.py
        echo "  Updated parallel_analyzer.py"
    fi
    
    # Remove file
    if [ -f "gpu_phase_lock.py" ]; then
        rm -v gpu_phase_lock.py
        ((REMOVED_COUNT++))
    fi
    echo ""
else
    echo "Skipped gpu_phase_lock.py removal"
    echo ""
fi

# ============================================
# SUMMARY
# ============================================
echo "=========================================="
echo -e "${GREEN}Cleanup Complete!${NC}"
echo "=========================================="
echo ""
echo "Files/directories removed: $REMOVED_COUNT"
echo ""
echo "Kept (active in use):"
echo "  ✓ chunking_strategies.py (used in app.py)"
echo "  ✓ hyde_generator.py (experimental feature in app.py)"
echo "  ✓ parent_child_chunking.py (used in app.py)"
echo "  ✓ start_AI3_services.sh (PRODUCTION startup)"
echo ""
echo "Check archive/old_docs/ voor gearchiveerde documentatie"
echo ""
echo "Git status:"
git status --short | head -20
echo ""
echo "BELANGRIJK: Review changes voordat je commit!"
echo "  git diff"
echo "  git add -A"
echo "  git commit -m 'cleanup: remove obsolete files and backups'"
