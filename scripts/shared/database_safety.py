from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine import URL

from scripts.shared.env import read_env_file

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def database_identity(url: str) -> tuple[str, int, str]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("Database URL must use postgres:// or postgresql://")
    query = parse_qs(parsed.query)
    if {"host", "hostaddr", "port", "dbname", "service", "servicefile"} & query.keys():
        raise ValueError("Database URL must not override its target through query parameters")
    host = parsed.hostname
    if not host or parsed.fragment:
        raise ValueError("Database URL requires an explicit host and no fragment")
    if "," in host:
        raise ValueError("Database URL must identify a single host")
    name = unquote(parsed.path.removeprefix("/"))
    if not name or "/" in name:
        raise ValueError("Database URL must identify one database")
    return ("localhost" if host in LOOPBACK_HOSTS else host.lower(), parsed.port or 5432, name)


def validate_database_target(app_env: str, url: str, production_url: str = "") -> None:
    if app_env not in {"development", "test", "production"}:
        raise ValueError("APP_ENV must be development, test, or production")
    host, port, name = database_identity(url)
    if app_env == "test" and (host != "localhost" or not name.endswith("_test")):
        raise ValueError("Tests require a loopback PostgreSQL database whose name ends in _test")
    if app_env == "production" and name.endswith("_test"):
        raise ValueError("Production cannot use a test database")
    if app_env != "production" and production_url and database_identity(production_url) == (host, port, name):
        raise ValueError(f"{app_env} database target matches production; refusing to connect")


def production_database_url(root: Path, environ: dict[str, str]) -> str:
    return environ.get("DATABASE_URL_PRODUCTION") or read_env_file(root / ".env.production").get("DATABASE_URL_PRODUCTION", "")


def sqlalchemy_url(url: str) -> URL:
    from sqlalchemy.engine import make_url
    database_identity(url)
    # Match the application's installed driver independently of SQLAlchemy defaults.
    return make_url(url).set(drivername="postgresql+psycopg2")


def validate_certificate(url: str) -> None:
    cert = parse_qs(urlsplit(url).query).get("sslrootcert", [])
    if cert and cert[0] != "system" and not Path(cert[0]).expanduser().is_file():
        raise ValueError("Database sslrootcert does not exist on this host; update the selected .env file to the native certificate path")


def validate_memory_target(root: Path, env: dict[str, str]) -> None:
    app_env = env["APP_ENV"]
    backend = env.get("MEMORY_BACKEND", "lancedb")
    production = {**read_env_file(root / ".env.default"), **read_env_file(root / ".env.production")}
    if app_env == "production" and backend == "lancedb":
        path = Path(env["MEMORY_STORE_PATH"]).expanduser()
        if not path.is_absolute() or not path.is_dir() or not any(path.iterdir()):
            raise ValueError("Production LanceDB requires an absolute MEMORY_STORE_PATH containing the existing migrated store; refusing to create an empty production store")
    if app_env != "production" and backend == "lancedb":
        current = Path(env["MEMORY_STORE_PATH"]).expanduser().resolve()
        prod_path = Path(production.get("MEMORY_STORE_PATH", str(root / "memory_store/production"))).expanduser().resolve()
        if current == prod_path:
            raise ValueError(f"{app_env} memory path matches production; refusing to open it")
    if app_env != "production" and backend == "pinecone" and production.get("MEMORY_BACKEND", "lancedb") == "pinecone":
        if env.get("PINECONE_INDEX", "agent-smith-memories") == production.get("PINECONE_INDEX", "agent-smith-memories"):
            raise ValueError(f"{app_env} Pinecone index matches production; configure a separate index")
