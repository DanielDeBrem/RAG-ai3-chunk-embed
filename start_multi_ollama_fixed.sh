#!/bin/bash
# Start meerdere Ollama instances, elk op eigen GPU
# Alle instances delen dezelfde model directory!

set -e

echo "=== Multi-GPU Ollama Setup ==="

# Stop systemd ollama
echo "Stopping systemd ollama..."
sudo systemctl stop ollama 2>/dev/null || true
pkill -9 -f "ollama serve" 2>/dev/null || true
sleep 3

# Configuratie
BASE_PORT=11434
MODEL_DIR="/usr/share/ollama/.ollama"  # Waar de modellen staan!
NUM_GPUS=8

# Maak logs directory
mkdir -p /home/daniel/Projects/RAG-ai3-chunk-embed/logs/ollama

echo "Starting $NUM_GPUS Ollama instances (sharing models from $MODEL_DIR)..."

for i in $(seq 0 $((NUM_GPUS-1))); do
    PORT=$((BASE_PORT + i))
    LOG_FILE="/home/daniel/Projects/RAG-ai3-chunk-embed/logs/ollama/ollama_gpu${i}.log"
    
    echo "  GPU $i -> port $PORT"
    
    # Start Ollama met specifieke GPU en shared model directory
    CUDA_VISIBLE_DEVICES=$i \
    OLLAMA_HOST="0.0.0.0:$PORT" \
    OLLAMA_MODELS="$MODEL_DIR/models" \
        nohup ollama serve > "$LOG_FILE" 2>&1 &
    
    sleep 1
done

echo ""
echo "Waiting for instances to start..."
sleep 5

# Check status
echo ""
echo "=== Instance Status ==="
for i in $(seq 0 $((NUM_GPUS-1))); do
    PORT=$((BASE_PORT + i))
    MODELS=$(curl -s "http://localhost:$PORT/api/tags" 2>/dev/null | jq -r '.models | length' 2>/dev/null || echo "0")
    echo "  GPU $i (port $PORT): $MODELS modellen"
done

echo ""
echo "=== GPU Status ==="
nvidia-smi --query-gpu=index,temperature.gpu,memory.used --format=csv

echo ""
echo "Done! Set OLLAMA_MULTI_GPU=true in parallel_analyzer.py"
