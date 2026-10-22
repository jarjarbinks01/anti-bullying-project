#!/bin/zsh
export PYTHONPYCACHEPREFIX="$HOME/Library/Application Support/HKU-Study2-Runtime/pycache"
cd "${0:A:h}" || exit 1
./.venv/bin/python -m study2 static-export
result=$?
if [ "$result" -eq 0 ]; then
  open "static_dashboard/index.html"
fi
exit "$result"
