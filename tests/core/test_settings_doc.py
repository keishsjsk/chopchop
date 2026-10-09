"""docs/settings.md собирается из схемы и не должен от неё отставать."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_settings_doc_is_up_to_date() -> None:
    spec = importlib.util.spec_from_file_location(
        "generate_settings_doc", ROOT / "docs" / "generate_settings_doc.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = (ROOT / "docs" / "settings.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == module.build().replace("\r\n", "\n"), (
        "docs/settings.md устарел: python docs/generate_settings_doc.py"
    )
