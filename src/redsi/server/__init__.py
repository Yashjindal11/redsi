"""Optional web API and dashboard (``pip install 'redsi[web]'``)."""

from redsi.server.app import create_app

__all__ = ["create_app"]
