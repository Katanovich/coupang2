#!/bin/zsh
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
(sleep 2 && open http://localhost:8501) &
.venv/bin/streamlit run app.py
