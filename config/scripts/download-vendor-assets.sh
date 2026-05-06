#!/bin/bash
# Download all CDN dependencies for offline operation.
# Run once on the target machine with internet access.
set -e

VENDOR="/opt/bcm/src/dashboard/web/assets/vendor"
mkdir -p "$VENDOR/leaflet/images"

echo "Downloading Tailwind CSS..."
curl -sL "https://cdn.tailwindcss.com?plugins=forms,container-queries" -o "$VENDOR/tailwind.js"

echo "Downloading Leaflet..."
curl -sL "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" -o "$VENDOR/leaflet/leaflet.js"
curl -sL "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" -o "$VENDOR/leaflet/leaflet.css"
curl -sL "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png" -o "$VENDOR/leaflet/images/marker-icon.png"
curl -sL "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png" -o "$VENDOR/leaflet/images/marker-icon-2x.png"
curl -sL "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png" -o "$VENDOR/leaflet/images/marker-shadow.png"
curl -sL "https://unpkg.com/leaflet@1.9.4/dist/images/layers.png" -o "$VENDOR/leaflet/images/layers.png"
curl -sL "https://unpkg.com/leaflet@1.9.4/dist/images/layers-2x.png" -o "$VENDOR/leaflet/images/layers-2x.png"

echo "Verifying downloads..."
for f in "$VENDOR/tailwind.js" "$VENDOR/leaflet/leaflet.js" "$VENDOR/leaflet/leaflet.css"; do
    SIZE=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f")
    if [ "$SIZE" -lt 1000 ]; then
        echo "ERROR: $f is only ${SIZE} bytes — download failed"
        exit 1
    fi
done

echo "Done. All vendor assets downloaded to $VENDOR"
echo "Tailwind: $(wc -c < "$VENDOR/tailwind.js") bytes"
echo "Leaflet JS: $(wc -c < "$VENDOR/leaflet/leaflet.js") bytes"
