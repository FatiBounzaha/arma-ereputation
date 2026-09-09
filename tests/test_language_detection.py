import os
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from backend.processing.language_detection import detect_language


def test_detect_french():
    assert detect_language("La collecte des déchets dans le quartier est en retard") == "fr"


def test_detect_arabic():
    assert detect_language("تأخر جمع النفايات في المدينة") == "ar"


def test_detect_darija_arabic():
    assert detect_language("واش كاين شي حل لهاد مشكل ديال النظافة") == "darija"


def test_detect_darija_latin():
    assert detect_language("wach kayn chi 7al hadchi bzaf") == "darija"
