#!/usr/bin/env bash
# Сборка AppImage для Linux (x86_64): ./packaging/build_appimage.sh [версия]
# Нужны: Python с зависимостями (pip install -e ".[build]"), libmpv2 (apt install libmpv2), curl.
# Собирайте на самой старой системе, которую хотите поддерживать: AppImage требует не меньший glibc.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:-$(python -c 'import chopchop; print(chopchop.__version__)')}"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
echo "CHOPCHOP ${VERSION}"

python packaging/generate.py
if [ ! -x build/binaries/bin/ffmpeg ]; then
  python packaging/fetch_binaries.py --platform linux --out build/binaries
fi
export CHOPCHOP_BINARIES="${PWD}/build/binaries"

rm -rf dist AppDir
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller packaging/chopchop.spec

cp LICENSE THIRD_PARTY_NOTICES.md dist/CHOPCHOP/

# самопроверка собранной программы: Qt, Pillow, ffmpeg, ffprobe и libmpv должны загружаться
QT_QPA_PLATFORM=offscreen dist/CHOPCHOP/chopchop --self-check build/self-check.json || true
cat build/self-check.json
python - <<'PY'
import json, sys
report = json.load(open("build/self-check.json", encoding="utf-8"))
sys.exit(0 if report["ok"] else 1)
PY

# каталог AppDir: программа целиком в usr/lib/chopchop, запуск через AppRun
mkdir -p AppDir/usr/lib AppDir/usr/bin AppDir/usr/share/applications \
         AppDir/usr/share/icons/hicolor/256x256/apps
cp -a dist/CHOPCHOP AppDir/usr/lib/chopchop
cp packaging/AppRun AppDir/AppRun
chmod +x AppDir/AppRun
printf '#!/bin/sh\nexec "$(dirname "$(readlink -f "$0")")/../lib/chopchop/chopchop" "$@"\n' > AppDir/usr/bin/chopchop
chmod +x AppDir/usr/bin/chopchop
cp packaging/chopchop.desktop AppDir/chopchop.desktop
cp packaging/chopchop.desktop AppDir/usr/share/applications/chopchop.desktop
cp resources/icons/chopchop.png AppDir/chopchop.png
cp resources/icons/chopchop.png AppDir/usr/share/icons/hicolor/256x256/apps/chopchop.png
ln -sf chopchop.png AppDir/.DirIcon

TOOL="build/appimagetool.AppImage"
if [ ! -f "$TOOL" ]; then
  curl -sSfL "$APPIMAGETOOL_URL" -o "$TOOL"
fi
echo "${APPIMAGETOOL_SHA256}  ${TOOL}" | sha256sum -c -
chmod +x "$TOOL"

OUT="dist/CHOPCHOP-${VERSION}-x86_64.AppImage"
# --appimage-extract-and-run: чтобы инструмент работал без FUSE (например, на сервере CI)
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream AppDir "$OUT"
chmod +x "$OUT"

# проверка готового AppImage без FUSE
APPIMAGE_EXTRACT_AND_RUN=1 QT_QPA_PLATFORM=offscreen "$OUT" --self-check build/appimage-self-check.json || true
cat build/appimage-self-check.json
python - <<'PY'
import json, sys
report = json.load(open("build/appimage-self-check.json", encoding="utf-8"))
sys.exit(0 if report["ok"] else 1)
PY
ls -lh dist
