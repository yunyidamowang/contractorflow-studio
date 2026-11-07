#!/bin/zsh
cd "${0:A:h}"
.venv/bin/python -m automation.dispatcher stop
