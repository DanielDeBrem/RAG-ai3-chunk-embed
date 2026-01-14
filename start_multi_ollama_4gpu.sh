#!/bin/bash
# Start 4 Ollama instances, elk op eigen GPU (GPU 0-3)
# Laat GPU 4-7 vrij voor embedding/reranking

# Stop bestaande Ollama instances
echo "Stopping existing Ollama instances..."
pkill -f "ollama serve" 2>/dev/null
sleep 2

# Configuratie - alleen 4 GPU's voor LLM
BASE_PORT=11434
NUM_GPUS=4  # GPU 0-3 voor Ollama
MODEL="${OLLAMA_MODEL:-llama3.1:8b}"

# Maak logs directory
mkdir -p /home/daniel/Projects/RAG-ai3-chunk-embed/logs/ollama

echo "Starting $NUM_GPUS Ollama instances on GPU 0-3..."
echo "(GPU 4-7 blijven vrij voor embedding)"

for i in $(seq 0 $((NUM_GPUS-1))); do
    PORT=$((BASE_PORT + i))
    LOG_FILE="/home/daniel/Projects/RAG-ai3-chunk-embed/logs/ollama/ollama_gpu${i}.log"
    
    echo "  GPU $i -> port $PORT"
    
    # Start Ollama met specifieke GPU
    # OLLAMA_KEEP_ALIVE=0 zorgt dat model direct unloadt na request
    CUDA_VISIBLE_DEVICES=$i \
    OLLAMA_HOST="0.0.0.0:$PORT" \
    OLLAMA_KEEP_ALIVE="0" \
        nohup ollama serve > "$LOG_FILE" 2>&1 &
    
    sleep 1
done

echo ""
echo "Waiting for instances to start..."
sleep 5

# Health check
echo "=== Health Check ==="
for i in $(seq 0 $((NUM_GPUS-1))); do
    PORT=$((BASE_PORT + i))
    STATUS=$(curl -s "http://localhost:$PORT/api/tags" > /dev/null 2>&1 && echo "✓ OK" || echo "✗ NOT READY")
    echo "  GPU $i: http://localhost:$PORT  $STATUS"
done

echo ""
echo "=== Multi-Ollama Setup Complete (4 GPU's) ==="
echo ""
echo "Ollama op GPU 0-3, poort 11434-11437"
echo "GPU 4-7 vrij voor embedding/reranking"
echo ""
echo "Set deze environment variables in services:"
echo "  export OLLAMA_MULTI_GPU=true"
echo "  export OLLAMA_NUM_INSTANCES=4"
echo "  export OLLAMA_BASE_PORT=11434"
