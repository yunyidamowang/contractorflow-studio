#!/bin/zsh
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  echo "Environment missing. See README.md for initial setup."
  read
  exit 1
fi
.venv/bin/python -c 'from app.main import init; init()'
printf '\nLocal Demo workspace key (paste into Unlock field):\n'
cat data/.token
printf '\n\nOpen http://127.0.0.1:8765/studio · Ctrl+C stops the server.\n'
open http://127.0.0.1:8765/studio
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
