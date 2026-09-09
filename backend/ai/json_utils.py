from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(raw_output: str) -> dict[str, Any]:
    """Extrait le premier objet JSON valide d'une sortie LLM.

    Tolère les blocs ```json``` et un court texte parasite avant/après le JSON,
    sans tenter de réparer silencieusement une réponse tronquée.
    """

    cleaned = (raw_output or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    try:
        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            raise RuntimeError("Un objet JSON était attendu.")
        return payload
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start < 0:
        raise RuntimeError(f"Aucun objet JSON trouvé dans la réponse : {raw_output}")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start:index + 1]
                try:
                    payload = json.loads(candidate)
                except json.JSONDecodeError as error:
                    raise RuntimeError(
                        f"Objet JSON trouvé mais invalide : {candidate}"
                    ) from error
                if not isinstance(payload, dict):
                    raise RuntimeError("Un objet JSON était attendu.")
                return payload

    raise RuntimeError(
        "Réponse JSON incomplète ou tronquée. Relancer l'appel LLM avec une limite de tokens suffisante."
    )


def positive_int_env(name: str, default: int, minimum: int = 1, maximum: int = 10000) -> int:
    """Lit un entier positif borné depuis l'environnement."""
    import os

    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))
