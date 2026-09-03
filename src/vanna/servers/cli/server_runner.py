"""
CLI for running Vanna Agents servers with example agents.
"""

import importlib
import json
import os
from typing import Dict, Optional, Any, Tuple, cast, TextIO, Union

import click

from ...core import Agent, AgentConfig
from ...core.agent.config import BusinessConfig
from ...tools.file_system import (
    EditFileTool,
    ListFilesTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from ...tools.python import PipInstallTool, RunPythonFileTool

# Optional tools selectable via the EXTRA_TOOLS env var (comma-separated
# names); classes are looked up here, instantiation happens on demand so
# importing this module stays cheap.
_TOOL_CATALOG = {
    "list_files": ListFilesTool,
    "read_file": ReadFileTool,
    "write_file": WriteFileTool,
    "edit_file": EditFileTool,
    "search_files": SearchFilesTool,
    "run_python_file": RunPythonFileTool,
    "pip_install": PipInstallTool,
}


class ExampleAgentLoader:
    """Loads example agents for the CLI."""

    @staticmethod
    def list_available_examples() -> Dict[str, str]:
        """Return available examples with descriptions."""
        return {
            "mock_quickstart": "Basic agent with mock LLM service",
            "anthropic_quickstart": "Agent configured for Anthropic's Claude API",
            "openai_quickstart": "Agent configured for OpenAI's GPT models",
            "mock_custom_tool": "Agent with custom tool demonstration (mock LLM)",
            "mock_quota_example": "Agent with usage quota management (mock LLM)",
            "mock_rich_components_demo": "Rich components demonstration with cards, tasks, and progress (mock LLM)",
            "coding_agent_example": "Coding agent with file system tools (list, read, write files)",
            "email_auth_example": "Email-based authentication demonstration (mock LLM)",
            "claude_sqlite_example": "Claude agent with SQLite database querying capabilities",
            "mock_sqlite_example": "Mock agent with SQLite database demonstration",
        }

    @staticmethod
    def load_example_agent(example_name: str) -> Agent:
        """Load an example agent by name.

        Args:
            example_name: Name of the example to load

        Returns:
            Configured agent instance

        Raises:
            ValueError: If example not found or failed to load
        """
        try:
            # Import the example module
            module = importlib.import_module(f"vanna.examples.{example_name}")

            # Look for standard factory functions
            factory_functions = [
                "create_demo_agent",
                "create_agent",
                "create_basic_demo",
            ]

            for func_name in factory_functions:
                if hasattr(module, func_name):
                    factory = getattr(module, func_name)
                    return cast(Agent, factory())

            # Look for module-level agent instances
            if hasattr(module, "main_agent"):
                return cast(Agent, module.main_agent)

            raise AttributeError(f"No agent factory found in {example_name}")

        except ImportError as e:
            raise ValueError(f"Example '{example_name}' not found: {e}")
        except Exception as e:
            raise ValueError(f"Failed to load example '{example_name}': {e}")


_DEFAULT_APP_CONFIG_PATH = "config/app.json"
_DEFAULT_CONVERSATION_DB_URL = "sqlite:///data/db/conversations.db"

# Keys allowed at the top level of the unified app config; anything
# else is reported so typos never fail silently.
_APP_CONFIG_KEYS = {
    "llm",
    "agent",
    "storage",
    "tools",
}


def _load_app_config() -> Dict[str, Any]:
    """Load the unified application config from a single JSON file.

    File format (config/app.json)::

        {
          "llm": {
            "active": "innolight",
            "instances": {
              "innolight": {"type": "openai", "api_key": "...",
                             "base_url": "...", "model": "..."},
              "local_ollama": {"type": "ollama", "host": "...", "model": "..."}
            }
          },
          "agent": {"max_tool_iterations": 10, "temperature": 0.7},
          "storage": {
            "project": {
              "conversation_db": {
                "active": "local_sqlite",
                "instances": {"local_sqlite":
                              {"url": "sqlite:///data/db/conversations.db"}}
              },
              "vector_db": {
                "active": "faiss_local",
                "instances": {"faiss_local": {"backend": "faiss"}}
              }
            },
            "businesses": [
              {"id": "biz_a",
               "enabled": true,
               "database": {"url": "sqlite:///a.db"},
               "schema_vector": {"namespace": "ns_a", "backend": null,
                                 "embedding_model_path": "models/bge"}}
            ]
          },
          "tools": {"extra": ["run_python_file"]}
        }

    Single-slot sections (llm / conversation_db / vector_db) select their
    instance via ``active``; unselected instances are reserved (validated
    but not instantiated). The ``businesses`` collection is multi-instance
    and filtered by ``enabled`` (defaults to True); there is no default
    fallback business — requests must carry a matching business_id.

    Path defaults to ``config/app.json`` (override with the
    ``APP_CONFIG_PATH`` env var). A missing file yields an empty dict
    (built-in defaults apply, info log); a malformed file aborts
    startup with a clear error so misconfiguration is never silent.

    Returns:
        Raw config dict (may be empty)
    """
    path = os.getenv("APP_CONFIG_PATH") or _DEFAULT_APP_CONFIG_PATH
    if not os.path.exists(path):
        click.echo(
            f"[info] App config not found at {path}; using built-in defaults",
            err=True,
        )
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Failed to read app config {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError(f"App config {path} must be a JSON object")
    unknown = sorted(set(raw) - _APP_CONFIG_KEYS)
    if unknown:
        click.echo(
            f"[warn] Unknown keys in {path}: {', '.join(unknown)} (ignored)",
            err=True,
        )
    return raw


def _resolve_active_instance(
    section_name: str, section: Any
) -> Tuple[str, Dict[str, Any]]:
    """Resolve the ``active`` instance of a single-slot config section.

    Returns (active_key, instance_dict). Raises ValueError when the
    section is present but malformed (active missing/unknown, instances
    not an object).
    """
    if not isinstance(section, dict):
        raise ValueError(f"App config '{section_name}' must be a JSON object")
    active = section.get("active")
    instances = section.get("instances")
    if not isinstance(instances, dict) or not instances:
        raise ValueError(
            f"App config '{section_name}.instances' must be a non-empty "
            "JSON object of named instances"
        )
    if not active:
        raise ValueError(
            f"App config '{section_name}.active' is required when the "
            "section is present (choose one of: "
            f"{', '.join(sorted(instances))})"
        )
    if active not in instances:
        raise ValueError(
            f"App config '{section_name}.active' references unknown "
            f"instance '{active}' (declared: {', '.join(sorted(instances))})"
        )
    return active, instances


def _create_llm_service(cfg: Dict[str, Any]) -> Any:
    """Build the LLM service from the ``llm`` section (active/instances).

    Falls back to a mock LLM when the section is absent or incomplete so
    the server still runs out of the box; an unsupported active instance
    type aborts startup instead of silently swapping implementations.
    """
    from ...integrations.llm.mock import MockLlmService

    section = cfg.get("llm")
    if not section:
        click.echo(
            "[warn] App config has no 'llm' section; using mock LLM",
            err=True,
        )
        return MockLlmService(
            response_content="Hello! I'm a demo chatbot server. How can I help you?"
        )

    active, instances = _resolve_active_instance("llm", section)
    inst = instances[active]
    if not isinstance(inst, dict):
        raise ValueError(f"llm instance '{active}' must be a JSON object")
    llm_type = inst.get("type")
    if llm_type != "openai":
        raise ValueError(
            f"llm instance '{active}' has unsupported type "
            f"'{llm_type}' (only 'openai' is implemented)"
        )

    api_key = inst.get("api_key")
    base_url = inst.get("base_url")
    model = inst.get("model")
    if not api_key or not model:
        missing = [
            name
            for name, value in [
                ("api_key", api_key),
                ("model", model),
            ]
            if not value
        ]
        click.echo(
            f"[warn] llm instance '{active}' incomplete "
            f"(missing: {', '.join(missing)}); using mock LLM",
            err=True,
        )
        return MockLlmService(
            response_content="Hello! I'm a demo chatbot server. How can I help you?"
        )

    try:
        from ...integrations.llm.openai import OpenAILlmService

        llm_service = OpenAILlmService(
            model=model, api_key=api_key, base_url=base_url
        )
        target = f"{model}" + (f" @ {base_url}" if base_url else "")
        click.echo(f"✓ Using LLM '{active}': {target}")
        return llm_service
    except Exception as e:
        click.echo(
            f"[warn] OpenAI LLM unavailable ({e}); falling back to mock LLM",
            err=True,
        )
        return MockLlmService(
            response_content="Hello! I'm a demo chatbot server. How can I help you?"
        )


def _create_conversation_store(section: Any):
    """Create the conversation store from ``storage.project.conversation_db``.

    The active instance's URL selects the store. Only the sqlite scheme
    is implemented today; any other scheme aborts startup with a clear
    message instead of silently falling back, so an intended mysql/pgsql
    deployment never quietly writes to the default. Reserved (inactive)
    instances are not scheme-checked.
    """
    from ...integrations.local import SQLiteConversationStore

    url: Optional[str] = None
    if section:
        active, _instances = _resolve_active_instance(
            "storage.project.conversation_db", section
        )
        inst = section["instances"][active]
        if not isinstance(inst, dict):
            raise ValueError(
                f"conversation_db instance '{active}' must be a JSON object"
            )
        url = inst.get("url")
        if not url:
            raise ValueError(
                f"conversation_db instance '{active}' is missing 'url'"
            )
        click.echo(f"✓ Conversation store: instance '{active}'")
    else:
        url = _DEFAULT_CONVERSATION_DB_URL
        click.echo(
            f"[info] storage.project.conversation_db not set; using "
            f"default {url}",
            err=True,
        )

    if not url.startswith("sqlite:///"):
        scheme = url.split("://", 1)[0] if "://" in url else url
        raise ValueError(
            f"conversation_db URL scheme '{scheme}' is not supported yet; "
            "only sqlite is implemented "
            "(e.g. sqlite:///data/db/conversations.db)"
        )
    db_path = url[len("sqlite:///"):]
    if not db_path:
        raise ValueError("conversation_db sqlite path is empty")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    return SQLiteConversationStore(db_path=db_path)


def _resolve_vector_db(
    section: Any,
) -> Tuple[Optional["VectorStoreSettings"], Dict[str, Any]]:
    """Resolve ``storage.project.vector_db``.

    Returns (settings, instances): the active instance's resolved
    VectorStoreSettings (or None when the section is absent) plus the
    declared instances for later business schema_vector.backend reference
    resolution. Only "faiss" is implemented; an active instance with
    another backend aborts startup.
    """
    if not section:
        return None, {}
    from ...agents import VectorStoreSettings

    active, instances = _resolve_active_instance(
        "storage.project.vector_db", section
    )
    inst = instances[active]
    if not isinstance(inst, dict):
        raise ValueError(f"vector_db instance '{active}' must be a JSON object")
    backend = inst.get("backend")
    if backend != "faiss":
        raise ValueError(
            f"vector_db instance '{active}' has unsupported backend "
            f"'{backend}' (only 'faiss' is implemented)"
        )
    settings = VectorStoreSettings(
        backend=backend,
        memory_index_path=inst.get("memory_index_path"),
        schema_persist_dir=inst.get("schema_persist_dir"),
    )
    click.echo(f"✓ Vector DB: instance '{active}' (faiss)")
    return settings, instances


def _load_businesses(
    storage_cfg: Dict[str, Any], vector_instances: Dict[str, Any]
) -> Dict[str, BusinessConfig]:
    """Parse and validate the ``storage.businesses`` collection.

    Every entry (enabled or not) is structurally validated so switching
    a reserved business on never surfaces a broken config. Enabled
    businesses with an explicit ``schema_vector.backend`` must reference
    a declared vector_db instance whose backend is implemented. There
    is no fallback: at least one enabled business is required.

    Returns:
        Enabled business configurations keyed by business id
    """
    raw = storage_cfg.get("businesses")
    if raw is None or raw == []:
        raise ValueError(
            "App config must declare at least one enabled business in "
            "storage.businesses (text-to-SQL is unusable without one); "
            "requests are routed by business_id with no fallback"
        )
    if not isinstance(raw, list):
        raise ValueError(
            "App config 'storage.businesses' must be a JSON array of "
            "business objects"
        )
    all_businesses: Dict[str, BusinessConfig] = {}
    for index, item in enumerate(raw):
        try:
            business = BusinessConfig(**item)
        except Exception as e:
            raise ValueError(
                f"Invalid business entry #{index} in 'storage.businesses': {e}"
            ) from e
        if business.id in all_businesses:
            raise ValueError(f"Duplicate business id '{business.id}'")
        all_businesses[business.id] = business

    enabled = {
        business_id: business
        for business_id, business in all_businesses.items()
        if business.enabled
    }
    if not enabled:
        raise ValueError(
            "All businesses in storage.businesses are disabled; at least "
            "one must be enabled"
        )

    # Resolve explicit schema_vector.backend references against the
    # declared vector_db instances (None inherits the active instance).
    for business in enabled.values():
        backend = business.schema_vector.backend
        if backend is None:
            continue
        if backend not in vector_instances:
            raise ValueError(
                f"business '{business.id}' schema_vector.backend "
                f"'{backend}' is not declared in "
                "storage.project.vector_db.instances"
            )
        declared = vector_instances[backend]
        if not isinstance(declared, dict) or declared.get("backend") != "faiss":
            raise ValueError(
                f"business '{business.id}' references vector_db instance "
                f"'{backend}' whose backend is not implemented (only "
                "'faiss' is supported)"
            )

    disabled = sorted(set(all_businesses) - set(enabled))
    if disabled:
        click.echo(
            f"[info] Reserved (disabled) businesses: {', '.join(disabled)}",
            err=True,
        )
    return enabled


def _create_config_agent() -> Agent:
    """Create the default agent from the unified JSON app config.

    All configuration lives in a single JSON file (config/app.json by
    default; see ``_load_app_config``): LLM (active/instances), agent
    behavior parameters, project storage (conversation/vector) and the
    multi-business routing declarations.

    Returns:
        Configured Agent instance
    """
    cfg = _load_app_config()

    llm_service = _create_llm_service(cfg)

    from ...agents import create_basic_agent

    storage_cfg = cfg.get("storage") or {}
    if not isinstance(storage_cfg, dict):
        raise ValueError("App config 'storage' must be a JSON object")
    project_cfg = storage_cfg.get("project") or {}
    if not isinstance(project_cfg, dict):
        raise ValueError("App config 'storage.project' must be a JSON object")

    # Project storage: conversation store + vector backend selection.
    conversation_store = _create_conversation_store(
        project_cfg.get("conversation_db")
    )
    vector_store, vector_instances = _resolve_vector_db(
        project_cfg.get("vector_db")
    )

    # Agent behavior parameters (validated by AgentConfig's pydantic model).
    agent_cfg = cfg.get("agent") or {}
    if not isinstance(agent_cfg, dict):
        raise ValueError("App config 'agent' must be a JSON object")

    # Multi-business routing: no fallback, at least one enabled business.
    businesses = _load_businesses(storage_cfg, vector_instances)
    click.echo(
        f"✓ Multi-business routing enabled: {len(businesses)} business(es)"
    )
    embedding_model_path: Optional[str] = None
    for business_id, business in businesses.items():
        click.echo(
            f"    - {business_id}: db={business.database.url}, "
            f"namespace={business.effective_database_name()}, "
            f"vector={'inherit' if business.schema_vector.backend is None else business.schema_vector.backend}"
        )
        business_embedding = business.schema_vector.embedding_model_path
        if business_embedding:
            if embedding_model_path and embedding_model_path != business_embedding:
                click.echo(
                    "[warn] Businesses declare different embedding_model_path "
                    f"values; using '{embedding_model_path}'",
                    err=True,
                )
            else:
                embedding_model_path = business_embedding

    # Tool assembly from config (pure parsing; creation happens in Agent).
    tools_cfg = cfg.get("tools") or {}
    if not isinstance(tools_cfg, dict):
        raise ValueError("App config 'tools' must be a JSON object")
    extra_tools = []
    raw_tools = tools_cfg.get("extra") or []
    if not isinstance(raw_tools, list):
        raise ValueError("App config 'tools.extra' must be a JSON array of tool names")
    for tool_name in raw_tools:
        if tool_name not in _TOOL_CATALOG:
            raise ValueError(
                f"tools.extra contains unknown tool '{tool_name}'. "
                f"Available: {', '.join(sorted(_TOOL_CATALOG))}"
            )
        extra_tools.append(_TOOL_CATALOG[tool_name]())

    # agent memory defaults to FAISS-backed when faiss is installed
    # (see agents.create_basic_agent), otherwise in-memory demo memory.
    return create_basic_agent(
        llm_service,
        config=AgentConfig(
            businesses=businesses,
            **agent_cfg,
        ),
        extra_tools=extra_tools,
        vector_store=vector_store,
        embedding_model_path=embedding_model_path,
        conversation_store=conversation_store,
    )


@click.command()
@click.option(
    "--framework",
    type=click.Choice(["flask", "fastapi"]),
    default="fastapi",
    help="Web framework to use",
)
@click.option("--port", default=8000, help="Port to run server on")
@click.option("--host", default="0.0.0.0", help="Host to bind server to")
@click.option(
    "--example", help="Example agent to use (use --list-examples to see options)"
)
@click.option("--list-examples", is_flag=True, help="List available example agents")
@click.option(
    "--config", type=click.File("r"), help="JSON config file for server settings"
)
@click.option("--debug", is_flag=True, help="Enable debug mode")
@click.option(
    "--dev",
    is_flag=True,
    help="Enable development mode (load components from local assets)",
)
@click.option(
    "--static-folder", default=None, help="Static folder path for development mode"
)
@click.option(
    "--cdn-url",
    default="https://img.vanna.ai/chatbot-components.js",
    help="CDN URL for web components",
)
def main(
    framework: str,
    port: int,
    host: str,
    example: Optional[str],
    list_examples: bool,
    config: Optional[click.File],
    debug: bool,
    dev: bool,
    static_folder: Optional[str],
    cdn_url: str,
) -> None:
    """Run Vanna Agents server with optional example agent."""

    if list_examples:
        click.echo("Available example agents:")
        examples = ExampleAgentLoader.list_available_examples()
        for name, description in examples.items():
            click.echo(f"  {name:20} - {description}")
        return

    # Load configuration
    server_config = {}
    if config:
        server_config = json.load(cast(TextIO, config))

    # Set default static folder based on dev mode
    if static_folder is None:
        static_folder = "frontends/webcomponent/static" if dev else "static"

    # Add CLI options to config
    server_config.update(
        {
            "dev_mode": dev,
            "static_folder": static_folder,
            "cdn_url": cdn_url,
            "api_base_url": "",  # Can be overridden in config file
        }
    )

    # Create agent
    if example:
        try:
            agent = ExampleAgentLoader.load_example_agent(example)
            click.echo(f"✓ Loaded example agent: {example}")
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            return
    else:
        # Fallback: build agent from the unified JSON app config
        # (mock LLM when unconfigured)
        try:
            agent = _create_config_agent()
            click.echo(
                "✓ Using basic agent from config/app.json (use --example to specify different agent)"
            )
        except Exception as e:
            click.echo(f"Error: Could not create basic agent: {e}", err=True)
            return

    registered_tools = sorted(agent.tool_registry._tools)
    click.echo(
        "🔧 Auto-registered tools: "
        + (", ".join(registered_tools) if registered_tools else "(none)")
    )

    # Expose enabled business IDs to the index page so the business
    # selector can route chat requests with business_id.
    if agent.config.businesses:
        server_config["businesses"] = list(agent.config.businesses)
        click.echo(
            "💼 Business routing enabled: "
            + ", ".join(agent.config.businesses)
        )

    from ..flask.app import VannaFlaskServer
    from ..fastapi.app import VannaFastAPIServer

    # Create and run server
    server: Union[VannaFlaskServer, VannaFastAPIServer]
    if framework == "flask":
        server = VannaFlaskServer(agent, config=server_config)
        click.echo(f"🚀 Starting Flask server on http://{host}:{port}")
        if dev:
            click.echo(
                f"📦 Development mode: loading web components from ./{static_folder}/"
            )
        else:
            click.echo(f"🌍 Production mode: loading web components from CDN")
        try:
            server.run(host=host, port=port, debug=debug)
        except KeyboardInterrupt:
            click.echo("\n👋 Server stopped")
    else:
        server = VannaFastAPIServer(agent, config=server_config)
        click.echo(f"🚀 Starting FastAPI server on http://{host}:{port}")
        click.echo(f"📖 API docs available at http://{host}:{port}/docs")
        if dev:
            click.echo(
                f"📦 Development mode: loading web components from ./{static_folder}/"
            )
        else:
            click.echo(f"🌍 Production mode: loading web components from CDN")
        try:
            server.run(host=host, port=port)
        except KeyboardInterrupt:
            click.echo("\n👋 Server stopped")


if __name__ == "__main__":
    main()
