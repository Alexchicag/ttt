#!/usr/bin/env bash
# Bootstrap the little-rocky project environment
set -e

python3.11 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp -n .env.example .env || true
echo "Environment ready. Edit .env with your credentials."
