import sys
from pathlib import Path


# Rend le dossier racine importable lorsque ce script est lance directement.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database.connection import SessionLocal
from backend.services.facebook_retained_links_service import export_retained_facebook_links


def main() -> None:
    session = SessionLocal()
    try:
        result = export_retained_facebook_links(session)
        print(
            f"{result['count']} lien(s) Facebook retenu(s) "
            f"exporte(s) vers {result['path']}"
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
