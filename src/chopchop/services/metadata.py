"""Метаданные при экспорте: по умолчанию удаляются (EXIF, GPS, миниатюры, профиль камеры)."""

from PIL import Image

ORIENTATION_TAG = 0x0112


def exif_for_export(exif: Image.Exif | None, keep: bool) -> bytes | None:
    """EXIF для записи в файл; None — не писать ничего.

    Поворот из EXIF уже применён к пикселям при открытии, поэтому ориентация сбрасывается,
    иначе просмотрщики повернут готовую картинку второй раз.
    """
    if not keep or exif is None or len(exif) == 0:
        return None
    clean = Image.Exif()
    for tag, value in exif.items():
        clean[tag] = value
    clean[ORIENTATION_TAG] = 1
    return clean.tobytes()
