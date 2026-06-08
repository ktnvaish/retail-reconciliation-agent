"""FastAPI application factory and app context.

`build_context` wires the whole system once (config, DB, agent, templates) and
stores it on ``app.state`` so request handlers can reach it without re-building
anything per request.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from reconcile import __version__
from reconcile.agent.service import ReconciliationAgent, build_dependencies
from reconcile.agent.state import AgentDependencies
from reconcile.api.middleware import register_middleware
from reconcile.api.routes import register_routes
from reconcile.config import AppConfig, AppSettings, get_settings, load_app_config
from reconcile.db import create_db_engine, init_db
from reconcile.logging_setup import configure_logging

_API_DIR = Path(__file__).parent / "api"
_TEMPLATES_DIR = _API_DIR / "templates"
_STATIC_DIR = _API_DIR / "static"


@dataclass
class AppContext:
    """Process-wide collaborators built once at startup."""

    settings: AppSettings
    config: AppConfig
    engine: Engine
    session_factory: Callable[[], Session]
    deps: AgentDependencies
    agent: ReconciliationAgent
    templates: Jinja2Templates


def build_context(settings: AppSettings | None = None) -> AppContext:
    """Wire configuration, persistence, and the agent into an app context."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    config = load_app_config(settings)

    engine = create_db_engine(settings)
    init_db(engine)
    session_factory: Callable[[], Session] = sessionmaker(
        bind=engine, expire_on_commit=False, future=True
    )

    deps = build_dependencies(settings, config, session_factory)
    agent = ReconciliationAgent(deps)
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    return AppContext(
        settings=settings,
        config=config,
        engine=engine,
        session_factory=session_factory,
        deps=deps,
        agent=agent,
        templates=templates,
    )


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    context = build_context(settings)
    app = FastAPI(title="ReconcileFlow Agent", version=__version__)
    app.state.context = context

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    register_middleware(app)
    register_routes(app)
    return app
