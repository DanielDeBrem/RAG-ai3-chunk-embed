#!/bin/bash
# Setup MySQL test database for AI-3 tests

echo "Creating MySQL test database..."
sudo mysql <<EOF
DROP DATABASE IF EXISTS ai3_rag_test;
CREATE DATABASE ai3_rag_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Create user if not exists (or grant to existing user)
CREATE USER IF NOT EXISTS 'ai3test'@'localhost' IDENTIFIED BY 'ai3test123';
GRANT ALL PRIVILEGES ON ai3_rag_test.* TO 'ai3test'@'localhost';
FLUSH PRIVILEGES;

SELECT 'Database created successfully' AS status;
EOF

echo ""
echo "✅ Test database ready!"
echo "Connection string: mysql+pymysql://ai3test:ai3test123@localhost/ai3_rag_test"
echo ""
echo "To run tests:"
echo "  export DATABASE_URL='mysql+pymysql://ai3test:ai3test123@localhost/ai3_rag_test'"
echo "  pytest test_persistence.py -v"
