"""Central configuration for the Research Claim Auditor.

Every other module imports from here. Loads .env once at import, exposes the
Anthropic client as a lazy singleton, and resolves data paths relative to this
file so the package works regardless of the caller's cwd.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
import anthropic

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
HACKATHON_REPO = ROOT / "oncosys-hackathon-challenge"
DATA_DIR = HACKATHON_REPO / "data" / "tcga-brca" / "raw"
MANIFEST_DIR = HACKATHON_REPO / "data" / "tcga-brca"

MODEL = "claude-sonnet-4-6"
MAX_RETRIES = 2
CONFIDENCE_THRESHOLD = 0.7

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "")
_client: Optional[object] = None


def get_client():
    """Return a lazily-constructed anthropic.Anthropic() singleton."""
    global _client
    if _client is None:


        if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "your_key_here":
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set in .env. "
                "Add your key before calling get_client()."
            )
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY,base_url=ANTHROPIC_BASE_URL)
    return _client
