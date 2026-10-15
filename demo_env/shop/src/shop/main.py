"""Entry point: `uvicorn shop.main:app`."""
from shop.app import create_app

app = create_app()
