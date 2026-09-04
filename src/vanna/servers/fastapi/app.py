"""
FastAPI server factory for Vanna Agents.
"""

import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ...core import Agent
from ..base import ChatHandler
from .routes import register_chat_routes
from .ddl_import import register_ddl_import_routes
from .auth_routes import register_auth_routes
from .conversation_routes import register_conversation_routes
from .schema_routes import register_schema_routes


class VannaFastAPIServer:
    """FastAPI server factory for Vanna Agents."""

    def __init__(self, agent: Agent, config: Optional[Dict[str, Any]] = None):
        """Initialize FastAPI server.

        Args:
            agent: The agent to serve (must have user_resolver configured)
            config: Optional server configuration
        """
        self.agent = agent
        self.config = config or {}
        self.chat_handler = ChatHandler(agent)

    def create_app(self) -> FastAPI:
        """Create configured FastAPI app.

        Returns:
            Configured FastAPI application
        """
        # Create FastAPI app
        app_config = self.config.get("fastapi", {})
        app = FastAPI(
            title="Vanna Agents API",
            description="API server for Vanna Agents framework",
            version="0.1.0",
            **app_config,
        )

        # Configure CORS if enabled
        cors_config = self.config.get("cors", {})
        if cors_config.get("enabled", True):
            cors_params = {k: v for k, v in cors_config.items() if k != "enabled"}

            # Set sensible defaults
            cors_params.setdefault("allow_origins", ["*"])
            cors_params.setdefault("allow_credentials", True)
            cors_params.setdefault("allow_methods", ["*"])
            cors_params.setdefault("allow_headers", ["*"])

            app.add_middleware(CORSMiddleware, **cors_params)

        # Add static file serving in dev mode
        dev_mode = self.config.get("dev_mode", False)
        if dev_mode:
            static_folder = self.config.get("static_folder", "static")
            # Skip if it's a URL (Vite HMR mode)
            if not static_folder.startswith("http"):
                static_folder = os.path.abspath(static_folder)
                print(f"[DEBUG] Static folder: {static_folder}, exists: {os.path.exists(static_folder)}")
                if os.path.exists(static_folder):
                    app.mount(
                        "/static",
                        StaticFiles(directory=static_folder),
                        name="static",
                    )
                    print(f"[DEBUG] Static files mounted at /static -> {static_folder}")
                else:
                    print(f"[DEBUG] Static folder does NOT exist: {static_folder}")

        # Register routes
        register_chat_routes(app, self.chat_handler, self.config)
        register_ddl_import_routes(app, self.agent)

        # Register new API routes
        admin_emails = self.config.get("admin_emails", [])
        register_auth_routes(app, self.agent, admin_emails=admin_emails)
        register_conversation_routes(app, self.agent)
        register_schema_routes(app, self.agent, admin_emails=admin_emails)

        # Add health check
        @app.get("/health")
        async def health_check() -> Dict[str, str]:
            return {"status": "healthy", "service": "vanna"}

        # Serve SPA static assets if built
        web_dist = self.config.get("web_dist", "frontends/web/dist")
        web_dist = os.path.abspath(web_dist)
        index_file = os.path.join(web_dist, "index.html")
        if os.path.exists(index_file):
            assets_dir = os.path.join(web_dist, "assets")
            if os.path.exists(assets_dir):
                app.mount("/assets", StaticFiles(directory=assets_dir), name="web-assets")

            @app.get("/app", include_in_schema=False)
            @app.get("/app/{full_path:path}", include_in_schema=False)
            async def spa_fallback(full_path: str = ""):
                candidate = os.path.join(web_dist, full_path)
                if full_path and os.path.isfile(candidate):
                    return FileResponse(candidate)
                return FileResponse(index_file)

        return app

    def run(self, **kwargs: Any) -> None:
        """Run the FastAPI server.

        This method automatically detects if running in an async environment
        (Jupyter, Colab, IPython, etc.) and:
        - Uses appropriate async handling for existing event loops
        - Sets up port forwarding if in Google Colab
        - Displays the correct URL for accessing the app

        Args:
            **kwargs: Arguments passed to uvicorn configuration
        """
        import sys
        import asyncio
        import uvicorn

        # Check if we're in an environment with a running event loop FIRST
        in_async_env = False
        try:
            asyncio.get_running_loop()
            in_async_env = True
        except RuntimeError:
            in_async_env = False

        # If in async environment, apply nest_asyncio BEFORE creating the app
        if in_async_env:
            try:
                import nest_asyncio

                nest_asyncio.apply()
            except ImportError:
                print("Warning: nest_asyncio not installed. Installing...")
                import subprocess

                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "nest_asyncio"]
                )
                import nest_asyncio

                nest_asyncio.apply()

        # Now create the app after nest_asyncio is applied
        app = self.create_app()

        # Set defaults
        run_kwargs = {"host": "0.0.0.0", "port": 8000, "log_level": "info", **kwargs}

        # Get the port and other config from run_kwargs
        port = run_kwargs.get("port", 8000)
        host = run_kwargs.get("host", "0.0.0.0")
        log_level = run_kwargs.get("log_level", "info")

        print("Your app is running at:")
        print(f"http://localhost:{port}")

        if in_async_env:
            # In Jupyter/Colab, create config with loop="asyncio" and use asyncio.run()
            # This matches the working pattern from Colab
            config = uvicorn.Config(
                app, host=host, port=port, log_level=log_level, loop="asyncio"
            )
            server = uvicorn.Server(config)
            asyncio.run(server.serve())
        else:
            # Normal execution outside of Jupyter/Colab
            uvicorn.run(app, **run_kwargs)
