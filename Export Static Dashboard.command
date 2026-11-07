#!/bin/zsh
cd "${0:A:h}" || exit 1
if [ "$#" -eq 0 ]; then
  ./.venv/bin/python -m study2 static-export --help
  exit $?
fi
./.venv/bin/python -m study2 static-export "$@"
