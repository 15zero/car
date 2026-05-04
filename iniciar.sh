#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
#  CarAnalyser — script de inicialização
#  Execute com:  bash iniciar.sh
# ──────────────────────────────────────────────────────────────────
set -e

PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    PYTHON="$cmd"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "❌ Python não encontrado. Instale Python 3.9+ e tente novamente."
  exit 1
fi

echo ""
echo "══════════════════════════════════════════════════"
echo "  CarAnalyser — Análise de Carros Usados"
echo "══════════════════════════════════════════════════"
echo ""

# Create venv if not exists
if [ ! -d "venv" ]; then
  echo "→ Criando ambiente virtual…"
  $PYTHON -m venv venv
fi

# Activate
if [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
  source venv/Scripts/activate
fi

# Install/upgrade dependencies
echo "→ Instalando dependências…"
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Create data dir
mkdir -p data

echo ""
echo "══════════════════════════════════════════════════"
echo "  Acesse:  http://localhost:5000"
echo "══════════════════════════════════════════════════"
echo ""

$PYTHON server.py
