"""
Tests for AI-3 DataFactory v1 persistence features.

Tests:
- Upsert → Retrieve: Verifies chunks are stored and retrievable
- Delete → Retrieve: Verifies deleted docs don't appear in search
"""
import os
import tempfile
import shutil
from typing import Generator
import pytest

from fastapi.testclient import TestClient

# Set test environment before imports
# Use MySQL for better concurrency (no locking issues)
# Run ./setup_test_db.sh first to create database
MYSQL_TEST_URL = os.getenv(
    'DATABASE_URL', 
    'mysql+pymysql://ai3test:ai3test123@localhost/ai3_rag_test'
)
os.environ['DATABASE_URL'] = MYSQL_TEST_URL
os.environ['INDEX_DIR'] = tempfile.mkdtemp(prefix='test_faiss_')
os.environ['DISABLE_STARTUP_EMBED_WARMUP'] = 'true'
os.environ['DISABLE_STARTUP_CORPUS_LOAD'] = 'true'
os.environ['AUTO_UNLOAD_EMBEDDER'] = 'false'

print(f"🔧 Using database: {MYSQL_TEST_URL.replace('ai3test123', '***')}")

from app_v1 import app
from models import init_db, get_session, Document, Chunk, Base
from job_queue import job_queue


@pytest.fixture(scope='function')
def client() -> Generator[TestClient, None, None]:
    """Test client with clean database per test."""
    # Initialize database
    init_db(MYSQL_TEST_URL)
    
    # Clean all tables (MySQL handles concurrency well)
    from models import engine
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    
    # Create test client
    with TestClient(app) as c:
        yield c
    
    # Cleanup after test
    index_dir = os.environ.get('INDEX_DIR')
    if index_dir and os.path.exists(index_dir):
        shutil.rmtree(index_dir, ignore_errors=True)
    
    # Recreate index dir for next test
    os.makedirs(index_dir, exist_ok=True)


def test_upsert_then_retrieve_returns_chunks(client: TestClient):
    """
    Test: Upsert document → Search → Verify chunks returned
    
    Verifies:
    - Document ingestion works
    - Chunks are created and stored
    - FAISS index is built
    - Search returns correct chunks
    """
    # Step 1: Upsert a document
    upsert_payload = {
        'tenant_id': 'test_tenant',
        'namespace': 'test_namespace',
        'doc_id': 'doc_001',
        'text': 'This is a test document. It has multiple sentences. We want to test chunking and retrieval.',
        'metadata': {'test': True},
        'chunk_strategy': 'default',
        'enrich_context': False  # Disable to speed up test
    }
    
    response = client.post('/v1/docs/upsert', json=upsert_payload)
    assert response.status_code == 200, f"Upsert failed: {response.text}"
    
    result = response.json()
    assert result['accepted'] == 1
    assert result['upserted_docs'] == 1
    assert result['skipped_docs'] == 0
    assert result['chunks_created'] > 0
    
    chunks_created = result['chunks_created']
    print(f"✓ Upserted document with {chunks_created} chunks")
    
    # Step 2: Verify document in database
    session = get_session()
    try:
        doc = session.query(Document).filter_by(doc_id='doc_001').first()
        assert doc is not None, "Document not found in database"
        assert doc.deleted_at is None, "Document should not be deleted"
        
        chunks = session.query(Chunk).filter_by(doc_id='doc_001', deleted_at=None).all()
        assert len(chunks) == chunks_created, f"Expected {chunks_created} chunks, found {len(chunks)}"
        print(f"✓ Verified {len(chunks)} chunks in database")
    finally:
        session.close()
    
    # Step 3: Search and verify retrieval
    search_payload = {
        'tenant_id': 'test_tenant',
        'namespace': 'test_namespace',
        'query': 'test document',
        'top_k': 5
    }
    
    response = client.post('/v1/search', json=search_payload)
    assert response.status_code == 200, f"Search failed: {response.text}"
    
    result = response.json()
    assert result['total_found'] > 0, "No chunks found in search"
    assert len(result['chunks']) > 0, "Empty chunks list"
    
    # Verify chunks belong to our document
    for chunk in result['chunks']:
        assert chunk['doc_id'] == 'doc_001'
        assert 'test' in chunk['text'].lower() or 'document' in chunk['text'].lower()
    
    print(f"✓ Search returned {result['total_found']} chunks")
    print("✅ test_upsert_then_retrieve_returns_chunks PASSED")


def test_delete_then_retrieve_excludes_doc(client: TestClient):
    """
    Test: Upsert → Delete → Search → Verify no chunks returned
    
    Verifies:
    - Document deletion works (soft delete)
    - Deleted chunks are filtered from search
    - Rebuild job is created
    """
    # Step 1: Upsert a document
    upsert_payload = {
        'tenant_id': 'test_tenant',
        'namespace': 'test_namespace',
        'doc_id': 'doc_to_delete',
        'text': 'This document will be deleted. It should not appear in search after deletion.',
        'metadata': {'test': True},
        'enrich_context': False
    }
    
    response = client.post('/v1/docs/upsert', json=upsert_payload)
    assert response.status_code == 200
    
    result = response.json()
    chunks_created = result['chunks_created']
    print(f"✓ Upserted document with {chunks_created} chunks")
    
    # Step 2: Verify it appears in search
    search_payload = {
        'tenant_id': 'test_tenant',
        'namespace': 'test_namespace',
        'query': 'deleted document',
        'top_k': 5
    }
    
    response = client.post('/v1/search', json=search_payload)
    assert response.status_code == 200
    
    result = response.json()
    assert result['total_found'] > 0, "Document not found before deletion"
    print(f"✓ Document found in search ({result['total_found']} chunks)")
    
    # Step 3: Delete the document
    response = client.delete(
        '/v1/docs/doc_to_delete',
        params={'tenant_id': 'test_tenant', 'namespace': 'test_namespace'}
    )
    assert response.status_code == 200, f"Delete failed: {response.text}"
    
    result = response.json()
    assert result['deleted'] is True
    assert result['chunks_deleted'] == chunks_created
    assert result['job_id'] is not None, "Rebuild job not created"
    
    job_id = result['job_id']
    print(f"✓ Document deleted, rebuild job: {job_id}")
    
    # Step 4: Verify document is soft-deleted in DB
    session = get_session()
    try:
        doc = session.query(Document).filter_by(doc_id='doc_to_delete').first()
        assert doc is not None, "Document should still exist (soft delete)"
        assert doc.deleted_at is not None, "Document should have deleted_at timestamp"
        
        chunks = session.query(Chunk).filter_by(doc_id='doc_to_delete').all()
        for chunk in chunks:
            assert chunk.deleted_at is not None, "All chunks should be marked deleted"
        
        print(f"✓ Verified soft delete in database")
    finally:
        session.close()
    
    # Step 5: Process rebuild job (simulate worker)
    from job_queue import process_job
    job = job_queue.get_next_pending_job()
    if job:
        print(f"✓ Processing rebuild job {job['job_id']}")
        process_job(job['job_id'], job['type'], job['payload'])
    
    # Step 6: Search again - should return no results
    response = client.post('/v1/search', json=search_payload)
    assert response.status_code == 200
    
    result = response.json()
    
    # After rebuild, deleted chunks should not appear
    # (or if they do, they shouldn't be from our deleted doc)
    for chunk in result.get('chunks', []):
        assert chunk['doc_id'] != 'doc_to_delete', \
            f"Deleted document chunk still appears in search: {chunk}"
    
    print(f"✓ Search returns {result['total_found']} chunks (deleted doc excluded)")
    print("✅ test_delete_then_retrieve_excludes_doc PASSED")


def test_idempotent_upsert(client: TestClient):
    """
    Test: Upsert same doc twice → Verify no duplicates
    
    Verifies idempotency of upsert operation.
    """
    payload = {
        'tenant_id': 'test_tenant',
        'namespace': 'test_namespace',
        'doc_id': 'idempotent_doc',
        'text': 'This is the same content twice.',
        'enrich_context': False
    }
    
    # First upsert
    response1 = client.post('/v1/docs/upsert', json=payload)
    assert response1.status_code == 200
    result1 = response1.json()
    chunks1 = result1['chunks_created']
    
    print(f"✓ First upsert: {chunks1} chunks created")
    
    # Second upsert (identical content)
    response2 = client.post('/v1/docs/upsert', json=payload)
    assert response2.status_code == 200
    result2 = response2.json()
    
    # Should skip (identical content)
    assert result2['skipped_docs'] == 1
    assert result2['upserted_docs'] == 0
    assert result2['chunks_created'] == 0
    
    print(f"✓ Second upsert: skipped (idempotent)")
    
    # Verify only one set of chunks in DB
    session = get_session()
    try:
        chunks = session.query(Chunk).filter_by(
            doc_id='idempotent_doc',
            deleted_at=None
        ).all()
        assert len(chunks) == chunks1, f"Expected {chunks1} chunks, found {len(chunks)}"
        print(f"✓ Verified no duplicates in database")
    finally:
        session.close()
    
    print("✅ test_idempotent_upsert PASSED")


def test_health_endpoint(client: TestClient):
    """Test health check endpoint."""
    response = client.get('/v1/health')
    assert response.status_code == 200
    
    result = response.json()
    assert 'ok' in result
    assert 'db_ok' in result
    assert 'index_store_ok' in result
    assert 'jobqueue_ok' in result
    assert 'build_info' in result
    
    print(f"✓ Health check: {'OK' if result['ok'] else 'FAILED'}")
    print("✅ test_health_endpoint PASSED")


if __name__ == '__main__':
    # Run tests with pytest
    import sys
    sys.exit(pytest.main([__file__, '-v', '-s']))
