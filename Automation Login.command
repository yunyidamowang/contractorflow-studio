#!/bin/zsh
cd "${0:A:h}"
.venv/bin/python -m automation.dispatcher init || exit 1
echo 'Sign in with ChatGPT for this project only. Do not choose API billing.'
CODEX_HOME="$PWD/.automation/codex-home" codex login
read '?Press Enter to close.'
