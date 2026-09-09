from logging.config import fileConfig
import os
import sys
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool


# Racine du projet : ARMA_PFA
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Permet à Alembic d'importer le dossier backend
sys.path.insert(0, str(PROJECT_ROOT))

# Charge les variables du fichier .env
load_dotenv(PROJECT_ROOT / ".env")


# Import de la base SQLAlchemy
from backend.database.connection import Base

# Cet import enregistre les 18 modèles dans Base.metadata
import backend.database.models  # noqa: F401, E402


config = context.config


# Configuration des logs Alembic
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# Récupération de l'URL PostgreSQL depuis .env
database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError(
        "DATABASE_URL est absente ou vide dans le fichier .env"
    )

# %% évite les problèmes si le mot de passe contient %
config.set_main_option(
    "sqlalchemy.url",
    database_url.replace("%", "%%"),
)


# Alembic comparera PostgreSQL avec ces modèles
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Exécute les migrations sans connexion directe.
    """

    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Exécute les migrations avec une connexion PostgreSQL.
    """

    configuration = config.get_section(
        config.config_ini_section,
        {},
    )

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()