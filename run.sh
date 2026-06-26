#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
streamlit run app.py --server.headless false --browser.gatherUsageStats false
