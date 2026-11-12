"""Puts the kit's harness and bindings on the path for the template's tests."""
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2] / "harness"
sys.path.insert(0, str(HARNESS))
