#!/bin/zsh
cd "${0:A:h}"
.venv/bin/python -m automation.dispatcher doctor || exit 1
echo 'Local poller: Mac must remain awake. Ctrl+C stops polling. Automation Stop.command also stops active work.'
exec .venv/bin/python -m automation.dispatcher watch
