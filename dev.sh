#!/usr/bin/env bash
# Starts the Python server (:8000) and the frontend (:5173). Open http://localhost:5173
# Ctrl+C stops both.
set -e
cd "$(dirname "$0")"
[ -d web/node_modules ] || (cd web && npm install)
(cd server && python3 -m uvicorn wish_broker.app:app --port 8000 --reload --reload-include '*.yaml' --reload-include '*.md') &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
cd web && npx vite --port 5173
