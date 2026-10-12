#!/bin/zsh
export PYTHONPYCACHEPREFIX="$HOME/Library/Application Support/HKU-Study2-Runtime/pycache"
cd "${0:A:h}" || exit 1
./.venv/bin/python -m study2 review-console
read "?按 Enter 關閉。"
