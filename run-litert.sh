#!/bin/sh
set -eu

MODE=full
HOST=127.0.0.1
PORT=8080
MODEL_ID=gemma4-e2b

usage() {
  echo "Uso: sh run-litert.sh [--mode full|limit] [--host DIRECCION]" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode|--host)
      [ "$#" -ge 2 ] || usage
      [ -n "$2" ] || usage
      case "$2" in --*) usage ;; esac
      case "$1" in
        --mode) MODE=$2 ;;
        --host) HOST=$2 ;;
      esac
      shift 2
      ;;
    *) usage ;;
  esac
done

case "$MODE" in
  full) THREADS=$(getconf _NPROCESSORS_ONLN) ;;
  limit) THREADS=1 ;;
  *) usage ;;
esac

command -v uvx >/dev/null 2>&1 || {
  echo "Falta uvx: instala uv antes de ejecutar este script." >&2
  exit 1
}

# LiteRT-LM keeps downloads in its own model registry, separate from GGUF files.
if ! uvx litert-lm describe "$MODEL_ID" >/dev/null 2>&1; then
  uvx litert-lm import \
    --from-huggingface-repo litert-community/gemma-4-E2B-it-litert-lm \
    gemma-4-E2B-it.litertlm "$MODEL_ID"
fi

CONFIG_FILE=$(mktemp "${TMPDIR:-/tmp}/rustio-litert.XXXXXX")
trap 'rm -f "$CONFIG_FILE"' 0
cat > "$CONFIG_FILE" <<EOF
{
  "models": {
    "$MODEL_ID": {
      "backend": "cpu",
      "vision_backend": "cpu",
      "cpu_thread_count": $THREADS,
      "max_num_tokens": 4096,
      "thinking": false
    }
  }
}
EOF

echo "Gemma 4 E2B: CPU, $THREADS hilos, razonamiento desactivado."
echo "API: http://$HOST:$PORT/v1 (modelo: $MODEL_ID)"
uvx litert-lm --config "$CONFIG_FILE" serve --host "$HOST" --port "$PORT"
