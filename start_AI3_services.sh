#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$HOME/Projects/RAG-ai3-chunk-embed"
VENV_DIR="$ROOT_DIR/.venv"

echo "== AI-3 service starter =="
echo "Project directory : $ROOT_DIR"
echo "Venv directory    : $VENV_DIR"
echo

if [ ! -d "$ROOT_DIR" ]; then
  echo "ERROR: $ROOT_DIR bestaat niet"
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "ERROR: venv niet gevonden op $VENV_DIR"
  exit 1
fi

cd "$ROOT_DIR"
source "$VENV_DIR/bin/activate"

mkdir -p "$ROOT_DIR/logs"

kill_port() {
  local PORT="$1"
  if command -v lsof >/dev/null 2>&1; then
    local PIDS
    PIDS=$(lsof -ti:"$PORT" || true)
    if [ -n "$PIDS" ]; then
      echo "Poort $PORT bezet door PID(s): $PIDS -> kill"
      kill $PIDS || true
      sleep 1
    fi
  else
    echo "Waarschuwing: lsof niet gevonden, skip kill_port voor $PORT"
  fi
}

echo "== Oude processen op poort 8000 / 9000 / 9100 / 9200 opruimen =="
kill_port 8000
kill_port 9000
kill_port 9100
kill_port 9200
echo

echo "== Start embedding_service op poort 8000 =="
nohup uvicorn embedding_service:app --host 0.0.0.0 --port 8000 \
  > "$ROOT_DIR/logs/embedding_8000.log" 2>&1 &
EMBED_PID=$!
echo "embedding_service PID: $EMBED_PID"
echo

echo "== Start datafactory app op poort 9000 =="
nohup uvicorn app:app --host 0.0.0.0 --port 9000 \
  > "$ROOT_DIR/logs/datafactory_9000.log" 2>&1 &
DATA_PID=$!
echo "datafactory PID: $DATA_PID"
echo

echo "== Start doc_analyzer_service op poort 9100 =="
nohup uvicorn doc_analyzer_service:app --host 0.0.0.0 --port 9100 \
  > "$ROOT_DIR/logs/analyzer_9100.log" 2>&1 &
ANALYZER_PID=$!
echo "doc_analyzer_service PID: $ANALYZER_PID"
echo

echo "== Start reranker_service op poort 9200 =="
nohup uvicorn reranker_service:app --host 0.0.0.0 --port 9200 \
  > "$ROOT_DIR/logs/reranker_9200.log" 2>&1 &
RERANK_PID=$!
echo "reranker_service PID: $RERANK_PID"
echo

echo "== Alles gestart =="
echo " - http://localhost:8000  (Embedding Service)"
echo " - http://localhost:9000  (DataFactory)"
echo " - http://localhost:9100  (Doc Analyzer)"
echo " - http://localhost:9200  (Reranker)"
echo
echo "== Externe toegang (vanaf AI-4) =="
echo " - http://10.10.10.13:8000"
echo " - http://10.10.10.13:9000"
echo " - http://10.10.10.13:9100"
echo " - http://10.10.10.13:9200"
