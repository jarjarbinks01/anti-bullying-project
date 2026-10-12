#!/bin/zsh
export PYTHONPYCACHEPREFIX="$HOME/Library/Application Support/HKU-Study2-Runtime/pycache"
cd "${0:A:h}" || exit 1
package_name="review_packages/review-$(date +%Y%m%d-%H%M%S).xlsx"
./.venv/bin/python -m study2 review-export --output "$package_name"
read "?按 Enter 關閉。"
