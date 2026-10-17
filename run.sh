#!/bin/sh
set -eu

MODE=full
case "$#" in
  0) ;;
  2)
    if [ "$1" != "--mode" ]; then
      echo "Uso: sh run.sh [--mode full|limit]" >&2
      exit 1
    fi
    MODE=$2
    ;;
  *)
    echo "Uso: sh run.sh [--mode full|limit]" >&2
    exit 1
    ;;
esac

case "$MODE" in
  full) THREADS=$(getconf _NPROCESSORS_ONLN) ;;
  limit) THREADS=1 ;;
  *)
    echo "Modo inválido: $MODE. Usa full o limit." >&2
    exit 1
    ;;
esac

MODEL_DIR="models"
MODEL_FILE="$MODEL_DIR/qwen3.5-2b-q4_k_m.gguf"
MODEL_URL="https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/main/Qwen3.5-2B-Q4_K_M.gguf"
MMPROJ_FILE="$MODEL_DIR/qwen3.5-2b-mmproj-f16.gguf"
MMPROJ_URL="https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/main/mmproj-F16.gguf"
PORT=8080
CTX_SIZE=4096

download() {
  if [ ! -f "$1" ]; then
    curl --fail --location --retry 3 --output "$1.part" "$2"
    mv "$1.part" "$1"
  fi
}

mkdir -p "$MODEL_DIR"
download "$MODEL_FILE" "$MODEL_URL"
download "$MMPROJ_FILE" "$MMPROJ_URL"

exec llama-server --model "$MODEL_FILE" --port "$PORT" --ctx-size "$CTX_SIZE" \
  --mmproj "$MMPROJ_FILE" --no-mmproj-offload \
  --jinja \
  --reasoning off \
  -ngl 0 \
  --threads "$THREADS" --threads-batch "$THREADS" -fa on \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --cont-batching
