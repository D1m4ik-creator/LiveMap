#!/bin/sh
set -eu

uv sync --frozen --no-dev
npm --prefix frontend ci
npm --prefix frontend run build
mkdir -p frontend-dist
cp -R frontend/dist/. frontend-dist/
