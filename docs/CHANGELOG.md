# Changelog - AI-3 RAG Services

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Current] - 2026-01-14

### 🎯 Major Documentation Cleanup & Reorganization

#### Added
- **OPERATIONS.md** - Comprehensive operations guide (GPU allocation, startup, monitoring)
- **API_REFERENCE.md** - Complete API documentation for all services
- **CHUNKING_GUIDE.md** - Consolidated chunking strategies guide
- **CHANGELOG.md** - This file, for tracking changes going forward

#### Changed
- **README.md** - Updated with correct GPU allocation (GPU 4-7 for Ollama)
- **ARCHITECTURE.md** - Enhanced with current architecture details
- Consolidated 29 markdown files → 8 core documentation files

#### Removed
- 16 historical/deprecated documentation files
- 4 duplicate startup scripts (kept only `start_AI3_services.sh`)
- Old backup files and directories (~500MB)

### 🚀 Service Improvements

#### Added
- Correct GPU pinning strategy:
  - GPU 0: DataFactory (BGE-m3 embeddings)
  - GPU 1: Reranker (BGE-reranker-v2-m3)
  - GPU 2: OCR Service (EasyOCR)
  - GPU 3: RESERVED (future expansion)
  - GPU 4-7: 4x Ollama (llama3.1:8b parallel enrichment)

#### Changed
- `start_AI3_services.sh` is now the single production startup script
- Ollama instances on ports 11435-11438 (not 11434-11437)
- Removed deprecated `start_multi_ollama_*` scripts

### 📚 Architecture Clarifications

**AI-3 Responsibilities:**
- ✅ Document parsing, OCR, chunking
- ✅ Embeddings and indexing (FAISS)
- ✅ Vector search + reranking
- ❌ NO final answer generation (AI-4's responsibility)

**AI-4 Responsibilities:**
- ✅ ALL final answers with llama3.1:70b
- ✅ Chat interface
- ✅ Data extraction and business logic

---

## [Previous Versions]

For historical changes prior to 2026-01-14, see Git history:
```bash
git log --oneline --since="2025-12-01" --until="2026-01-14"
```

---

## Future Roadmap

### Planned Features
- [ ] Enhanced chunking strategies (code, email, JSON/XML)
- [ ] Per-tenant strategy preferences
- [ ] Hot-reload configuration without restart
- [ ] Advanced parent-child chunking
- [ ] Streaming API for real-time processing

### Under Consideration
- [ ] Multi-language embedding support
- [ ] Custom reranker models
- [ ] Webhook system for AI-4 integration
- [ ] Distributed FAISS for horizontal scaling

---

## Contributing

When making changes:
1. Update relevant documentation
2. Add entry to this CHANGELOG
3. Test with `start_AI3_services.sh`
4. Verify all services with health checks

---

## Support

For issues or questions:
- Check **OPERATIONS.md** for common problems
- Review **API_REFERENCE.md** for API details
- See **ARCHITECTURE.md** for system design
- Consult **CHUNKING_GUIDE.md** for chunking strategies

---

**Last Updated:** 14 januari 2026
