#!/bin/zsh
cd "${0:A:h}"
.venv/bin/python -m automation.dispatcher init || exit 1
echo 'Use a fine-grained token for contractorflow-studio only: Contents, Issues, Pull requests read/write; no Actions/admin permission.'
read -rs 'task_token?Paste token (hidden), then Enter: '
printf '\n'
if [[ -z "$task_token" ]]; then
  echo 'No token saved.'
  exit 1
fi
umask 077
printf '%s' "$task_token" > .automation/github.token
unset task_token
chmod 600 .automation/github.token
echo 'Saved locally. Worker remains disabled; token was not printed.'
read '?Press Enter to close.'
