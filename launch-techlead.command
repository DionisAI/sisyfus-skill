#!/bin/zsh
set -eu
ROOT="${0:A:h}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
exec python3 -m sisyfus techlead hub --directory "$HOME/Documents/Sisyfus-TechLead/missions" --port 8781 --open
