#!/usr/bin/env bash
# BCM v8.5 — prekompilacja Tailwind CSS dla web frontendu.
#
# Frontend NIE używa już runtime'owego silnika Tailwind (tailwind.js,
# 419 KB JS kompilującego CSS w przeglądarce przy każdym otwarciu) —
# zamiast tego statyczny, zminifikowany arkusz jest generowany tutaj
# i commitowany do repo (assets/vendor/tailwind.css, ~37 KB).
#
# Uruchom TYLKO gdy dodasz nowe klasy Tailwind w js/ lub index.html:
#   ./config/scripts/build-frontend.sh
#
# Wymaga node/npm (npx pobierze tailwindcss@3 przy pierwszym użyciu).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WEB_DIR="$REPO_DIR/src/dashboard/web"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

cat > "$WORK_DIR/tailwind.config.js" <<EOF
// Lustrzana kopia dawnego inline tailwind.config z index.html.
module.exports = {
  darkMode: "class",
  content: [
    "$WEB_DIR/index.html",
    "$WEB_DIR/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        primary: "var(--color-primary)",
        accent: "var(--color-accent)",
        surface: "var(--color-surface)",
        "on-surface": "var(--color-on-surface)",
        "on-surface-variant": "var(--color-on-surface-variant)",
      },
      fontFamily: {
        display: ["Public Sans", "sans-serif"],
        body: ["Public Sans", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "0.25rem",
        lg: "0.5rem",
        xl: "0.75rem",
        full: "9999px",
      },
    },
  },
};
EOF

printf '@tailwind base;\n@tailwind components;\n@tailwind utilities;\n' > "$WORK_DIR/input.css"

cd "$WORK_DIR"
npx --yes tailwindcss@3.4.17 \
    -c tailwind.config.js \
    -i input.css \
    -o "$WEB_DIR/assets/vendor/tailwind.css" \
    --minify

echo "OK: $(wc -c < "$WEB_DIR/assets/vendor/tailwind.css") bajtów → $WEB_DIR/assets/vendor/tailwind.css"
