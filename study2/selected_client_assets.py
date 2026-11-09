"""Accepted selected-child browser sources, stored as readable package resources."""
from importlib.resources import files

_ASSETS = files("study2.presentation").joinpath("assets")
APP_JS = _ASSETS.joinpath('app.js').read_text(encoding="utf-8")
STYLES = _ASSETS.joinpath('app.css').read_text(encoding="utf-8")
QUALITY_JS = _ASSETS.joinpath('quality.js').read_text(encoding="utf-8")
SCOPE_JS = _ASSETS.joinpath('scope.js').read_text(encoding="utf-8")
