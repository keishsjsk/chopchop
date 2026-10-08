from pathlib import Path

from PIL import Image

from chopchop.viewer.image_loader import load_image


def test_loads_png(tmp_path: Path) -> None:
    path = tmp_path / "a.png"
    Image.new("RGB", (40, 20), "red").save(path)
    image = load_image(path)
    assert image is not None
    assert (image.width(), image.height()) == (40, 20)


def test_applies_exif_orientation(tmp_path: Path) -> None:
    path = tmp_path / "rot.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # повернуть на 90° по часовой
    Image.new("RGB", (40, 20), "blue").save(path, exif=exif)
    image = load_image(path)
    assert image is not None
    assert (image.width(), image.height()) == (20, 40)


def test_broken_file_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"not an image")
    assert load_image(path) is None


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_image(tmp_path / "nope.png") is None
