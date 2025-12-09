#!/usr/bin/env bash
set -euo pipefail

# Small helper to download DejaVu Sans TTFs into the project's fonts/ directory
# Usage: ./scripts/install_fonts.sh

FONT_DIR="$(dirname "${BASH_SOURCE[0]}")/../fonts"
mkdir -p "$FONT_DIR"

download() {
  url=$1
  dest=$2
  if [ -f "$dest" ]; then
    echo "Already present: $dest"
    return
  fi
  echo "Downloading $url -> $dest"
  curl -fSL "$url" -o "$dest"
  echo "Saved $dest"
}

# Attempt to source DejaVu from common system locations first
LOCAL_CANDIDATES=(
  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
  "/Library/Fonts/DejaVuSans.ttf"
  "/Library/Fonts/DejaVuSans-Bold.ttf"
)

for candidate in "${LOCAL_CANDIDATES[@]}"; do
  if [ -f "$candidate" ]; then
    dest="$FONT_DIR/$(basename "$candidate")"
    echo "Copying system font $candidate -> $dest"
    cp "$candidate" "$dest" || true
  fi
done

echo "Attempting remote downloads for DejaVu if not already present"

# URLs to try for DejaVu variants (include ?raw=true forms)
DEJAVU_URLS=(
  "https://github.com/dejavu-fonts/dejavu-fonts/raw/main/ttf/DejaVuSans.ttf"
  "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf"
  "https://github.com/dejavu-fonts/dejavu-fonts/blob/main/ttf/DejaVuSans.ttf?raw=true"
  "https://github.com/dejavu-fonts/dejavu-fonts/blob/master/ttf/DejaVuSans.ttf?raw=true"
)

DEJAVU_BOLD_URLS=(
  "https://github.com/dejavu-fonts/dejavu-fonts/raw/main/ttf/DejaVuSans-Bold.ttf"
  "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans-Bold.ttf"
  "https://github.com/dejavu-fonts/dejavu-fonts/blob/main/ttf/DejaVuSans-Bold.ttf?raw=true"
  "https://github.com/dejavu-fonts/dejavu-fonts/blob/master/ttf/DejaVuSans-Bold.ttf?raw=true"
)

for url in "${DEJAVU_URLS[@]}"; do
  if [ ! -s "$FONT_DIR/DejaVuSans.ttf" ]; then
    download "$url" "$FONT_DIR/DejaVuSans.ttf" || true
  fi
done

for url in "${DEJAVU_BOLD_URLS[@]}"; do
  if [ ! -s "$FONT_DIR/DejaVuSans-Bold.ttf" ]; then
    download "$url" "$FONT_DIR/DejaVuSans-Bold.ttf" || true
  fi
done

echo "Fonts present in $FONT_DIR (non-empty files):"
ls -l "$FONT_DIR" || true

# If DejaVu wasn't available, download a widely-available unicode font (Noto Sans) as fallback.
if [ ! -s "$FONT_DIR/DejaVuSans.ttf" ] || [ ! -s "$FONT_DIR/DejaVuSans-Bold.ttf" ]; then
  echo "DejaVu not available -> attempting NotoSans fallback"
  # Try multiple Noto locations (main repo and googlefonts mirror)
  download "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans-Regular.ttf" "$FONT_DIR/NotoSans-Regular.ttf" || true
  download "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans-Bold.ttf" "$FONT_DIR/NotoSans-Bold.ttf" || true
  # alternate repo path
  download "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf" "$FONT_DIR/NotoSans-Regular.ttf" || true
  download "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Bold.ttf" "$FONT_DIR/NotoSans-Bold.ttf" || true
fi

echo "Final contents of $FONT_DIR:"
ls -l "$FONT_DIR" || true
