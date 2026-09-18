"""Workbench API router for IT Helpdesk Operations Workbench (Console V2).

Connects frontend directly to real data:
- Real conversation turns & event logs from events.jsonl
- Real FAQs from data/ops/phase2/faqs.json
- Real documents and chunks from portal_state.json and chunks.json
- Real IT ticket dispatch & persistence in data/ops/tickets.json
"""

from __future__ import annotations

from .routes import register_workbench_routes

__all__ = ["register_workbench_routes"]
