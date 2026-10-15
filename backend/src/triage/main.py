"""Entry point: `uvicorn triage.main:app`."""
from triage.api import create_app

app = create_app()
