"""Signals' research agent: a separate service that investigates one wallet's trades with Claude.

It runs as its own process (``uvicorn signals.research.server:app``, ``Dockerfile.research``), never inside the
engine (``signals/app.py``): agent runs are long and read-heavy, and the engine is tuned so alerts come first.
See README, "Research agent", and AGENTS.md, "Research agent".
"""
