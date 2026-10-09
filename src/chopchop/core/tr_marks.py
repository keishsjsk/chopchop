"""Пометка строк для переводчика. lupdate находит вызовы по имени QT_TRANSLATE_NOOP."""


def QT_TRANSLATE_NOOP(_context: str, text: str) -> str:  # noqa: N802
    """Возвращает строку как есть: она переводится позже, в том месте, где показывается."""
    return text
