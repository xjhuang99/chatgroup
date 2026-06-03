#!/bin/bash
# Export Graphical_Abstract_1328x531.html → PNG (1328×531, 300 DPI equivalent)
# Requires ONE of: Google Chrome, Chromium, or weasyprint

set -e
cd "$(dirname "$0")"
HTML="Graphical_Abstract_1328x531.html"
OUT="Graphical_Abstract_1328x531.png"

if command -v google-chrome &>/dev/null; then CHROME=google-chrome
elif command -v chromium &>/dev/null; then CHROME=chromium
elif [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
  CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
else
  CHROME=""
fi

if [ -n "$CHROME" ]; then
  ABS_HTML="file://$(pwd)/$HTML"
  "$CHROME" --headless --disable-gpu --window-size=1328,531 \
    --screenshot="$OUT" "$ABS_HTML"
  echo "Saved: $OUT"
  sips -g pixelWidth -g pixelHeight "$OUT" 2>/dev/null || true
  exit 0
fi

if command -v weasyprint &>/dev/null; then
  weasyprint "$HTML" "${OUT%.png}.pdf"
  sips -s format png "${OUT%.png}.pdf" --out "$OUT" 2>/dev/null || \
    convert -density 300 "${OUT%.png}.pdf" "$OUT"
  echo "Saved: $OUT"
  exit 0
fi

echo "Install Google Chrome, or: pip install weasyprint"
echo "Or open $HTML in Chrome → F12 → select .canvas → Capture node screenshot"
exit 1
