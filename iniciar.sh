#!/usr/bin/env sh
# Estudio DIAN – lanzador para macOS / Linux
cd "$(dirname "$0")" || exit 1
if command -v git >/dev/null 2>&1 && [ -d .git ]; then
  echo "Buscando preguntas nuevas..."
  git pull --ff-only -q || echo "No se pudo actualizar; se usará la versión que ya tienes."
fi
python3 -c "import flask" 2>/dev/null || python3 -m pip install -r requirements.txt
echo "Estudio DIAN en http://127.0.0.1:5000 (Ctrl+C para detener)"
python3 app.py
