#!/bin/bash
# Start meerdere Ollama instances, elk op eigen GPU
# Dit lost het thermal throttling probleem op door werk te verdelen

# Stop bestaande Ollama instances
echo "Stopping existing Ollama instances..."
pkill -f "ollama serve" 2>/dev/null
sleep 2

# Configuratie
BASE_PORT=11434
NUM_GPUS=8
MODEL="llama3.1:8b"

# Maak logs directory
mkdir -p /home/daniel/Projects/RAG-ai3-chunk-embed/logs/ollama

echo "Starting $NUM_GPUS Ollama instances..."

for i in $(seq 0 $((NUM_GPUS-1))); do
    PORT=$((BASE_PORT + i))
    LOG_FILE="/home/daniel/Projects/RAG-ai3-chunk-embed/logs/ollama/ollama_gpu${i}.log"
    
    echo "  GPU $i -> port $PORT"
    
    # Start Ollama met specifieke GPU
    CUDA_VISIBLE_DEVICES=$i OLLAMA_HOST="0.0.0.0:$PORT" \
        nohup ollama serve > "$LOG_FILE" 2>&1 &
    
    sleep 1
done

echo ""
echo "Waiting for instances to start..."
sleep 5

# Preload model op elke instance
echo "Preloading model $MODEL on each instance..."
for i in $(seq 0 $((NUM_GPUS-1))); do
    PORT=$((BASE_PORT + i))
    echo "  Loading on port $PORT (GPU $i)..."
    
    # Warm up door een simpele request (model laden)
    curl -s -X POST "http://localhost:$PORT/api/generate" \
        -d "{\"model\": \"$MODEL\", \"prompt\": \"test\", \"stream\": false}" \
        > /dev/null 2>&1 &
done

wait
echo ""
echo "=== Multi-Ollama Setup Complete ==="
echo ""
echo "Ollama instances:"
for i in $(seq 0 $((NUM_GPUS-1))); do
    PORT=$((BASE_PORT + i))
    STATUS=$(curl -s "http://localhost:$PORT/api/tags" > /dev/null 2>&1 && echo "✓ OK" || echo "✗ NOT READY")
    echo "  GPU $i: http://localhost:$PORT  $STATUS"
done
echo ""
echo "Environment variables voor parallel_analyzer:"
echo "  export OLLAMA_MULTI_GPU=true"
echo "  export OLLAMA_BASE_PORT=11434"
echo "  export OLLAMA_NUM_INSTANCES=8"
