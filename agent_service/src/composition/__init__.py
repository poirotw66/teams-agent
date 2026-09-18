"""Composition root package.

Import concrete factory or ASGI modules directly, for example:

- ``composition.agent_app.create_agent_app``
- ``composition.agent_asgi:app``

This package init intentionally does not import app factories so loading one
service entrypoint cannot assemble the others.
"""
