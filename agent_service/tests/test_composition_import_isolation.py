"""Composition import isolation and ASGI entrypoint contracts."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest


def _purge_composition_modules() -> None:
    for name in list(sys.modules):
        if name == "composition" or name.startswith("composition."):
            del sys.modules[name]


def test_composition_package_init_does_not_eager_import_apps() -> None:
    _purge_composition_modules()
    import composition

    assert composition.__doc__
    assert "composition.agent_app" not in sys.modules
    assert "composition.backoffice_app" not in sys.modules
    assert "composition.portal_app" not in sys.modules
    assert "composition.agent_asgi" not in sys.modules
    assert "composition.backoffice_asgi" not in sys.modules
    assert "composition.portal_asgi" not in sys.modules


def test_import_agent_factory_does_not_load_other_services() -> None:
    _purge_composition_modules()
    from composition.agent_app import create_agent_app

    assert callable(create_agent_app)
    assert "composition.backoffice_app" not in sys.modules
    assert "composition.portal_app" not in sys.modules
    assert "composition.backoffice_asgi" not in sys.modules
    assert "composition.portal_asgi" not in sys.modules
    assert "composition.agent_asgi" not in sys.modules


def test_import_agent_asgi_does_not_build_other_service_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _purge_composition_modules()
    from composition import agent_app as agent_app_module

    sentinel = SimpleNamespace(title="agent-only")
    monkeypatch.setattr(
        agent_app_module,
        "create_agent_app",
        lambda settings=None: sentinel,
    )
    sys.modules.pop("composition.agent_asgi", None)

    from composition import agent_asgi

    assert agent_asgi.app is sentinel
    assert "composition.backoffice_asgi" not in sys.modules
    assert "composition.portal_asgi" not in sys.modules
    assert "composition.backoffice_app" not in sys.modules
    assert "composition.portal_app" not in sys.modules


def test_import_backoffice_asgi_does_not_build_other_service_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _purge_composition_modules()
    from composition import backoffice_app as backoffice_app_module

    sentinel = SimpleNamespace(title="backoffice-only")
    monkeypatch.setattr(
        backoffice_app_module,
        "create_backoffice_app",
        lambda settings=None, **kwargs: sentinel,
    )
    sys.modules.pop("composition.backoffice_asgi", None)

    from composition import backoffice_asgi

    assert backoffice_asgi.app is sentinel
    # Factory module may import portal_app for DI wiring; ASGI singletons must stay cold.
    assert "composition.agent_asgi" not in sys.modules
    assert "composition.portal_asgi" not in sys.modules
    assert "composition.agent_app" not in sys.modules


def test_import_portal_asgi_does_not_build_other_service_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _purge_composition_modules()
    from composition import portal_app as portal_app_module

    sentinel = SimpleNamespace(title="portal-only")
    monkeypatch.setattr(
        portal_app_module,
        "create_portal_app",
        lambda settings=None, **kwargs: sentinel,
    )
    sys.modules.pop("composition.portal_asgi", None)

    from composition import portal_asgi

    assert portal_asgi.app is sentinel
    assert "composition.agent_asgi" not in sys.modules
    assert "composition.backoffice_asgi" not in sys.modules
    assert "composition.agent_app" not in sys.modules
    assert "composition.backoffice_app" not in sys.modules


def test_domain_api_modules_expose_factory_without_module_app() -> None:
    from agent_service import api as agent_api
    from ai_ops_backoffice import api as backoffice_api
    from knowledge_portal import api as portal_api

    assert callable(agent_api.create_app)
    assert callable(backoffice_api.create_app)
    assert callable(portal_api.create_app)
    assert not hasattr(agent_api, "app")
    assert not hasattr(backoffice_api, "app")
    assert not hasattr(portal_api, "app")


def test_service_mains_point_at_composition_asgi_modules() -> None:
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src"
    expected = {
        "agent_service/main.py": "composition.agent_asgi:app",
        "ai_ops_backoffice/main.py": "composition.backoffice_asgi:app",
        "knowledge_portal/main.py": "composition.portal_asgi:app",
    }
    for relative, target in expected.items():
        source = (root / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        assert target in literals, relative
