"""Isolated-process bridge for reviewed local activation and recovery."""
from pathlib import Path
import sys

# -I intentionally ignores the working directory. Bind this installed checkout.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from study2.entrypoint import main, prepare_activation as prepare

if __name__ == '__main__':
    main()
