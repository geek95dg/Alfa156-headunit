#!/bin/bash
# Piper TTS + the Polish voice for modules.voice_announce
# (src/audio/voice_announce.py, src/audio/tts.py).
#
#   sudo bash /opt/bcm/config/scripts/install-piper.sh
#
# Called by setup-x86.sh and apply-fixes.sh; can be run on its own.
# Idempotent and NON-FATAL: every problem is a warning and the script exits
# 0 — without Piper BCM speaks with espeak-ng (installed by the callers),
# and without both it only shows the notifications.
#
# Security: every downloaded file is checked against the SHA-256 list
# config/scripts/piper-sha256.txt (plus the local supplement
# /etc/bcm/piper.sha256). A file without a listed hash is NOT installed —
# the script says how to add it — and a file whose hash differs is deleted.
# Downloads go to a private temporary directory, HTTPS only; the tarball is
# refused if it contains absolute paths or "..".
#
# Result (the defaults of voice_announce.piper_bin / voice_announce.model):
#   /opt/bcm/piper/piper/piper                         (binary + its libraries)
#   /opt/bcm/piper/voices/pl_PL-gosia-medium.onnx      (+ .onnx.json)
# /opt/bcm/piper is in .gitignore; cleanup-x86.sh removes it.
#
# Why gosia-medium (and not darkman-medium): a female voice with a higher
# pitch stands out better against engine/road noise and the bass of the
# music, which is what a short warning needs; "medium" is the best quality
# Piper has for Polish at a size (≈ 63 MB) and speed (well under 1 s per
# sentence on the M910q) that suit the car.
set -u

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo bash $0"; exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
DEST=${BCM_PIPER_DIR:-/opt/bcm/piper}
HASH_FILES="$SCRIPT_DIR/piper-sha256.txt /etc/bcm/piper.sha256"
PIPER_VERSION=2023.11.14-2
PIPER_TARBALL=piper_linux_x86_64.tar.gz
PIPER_URL="https://github.com/rhasspy/piper/releases/download/$PIPER_VERSION/$PIPER_TARBALL"
VOICE=pl_PL-gosia-medium
VOICE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pl/pl_PL/gosia/medium"

warn() { echo "    WARNING: $*"; }

# The listed hash of a file name ('' = not listed). Only well-formed lines
# count; the last match wins, so the local supplement can correct an entry.
expected_hash() {
    local name=$1 file
    for file in $HASH_FILES; do
        [ -r "$file" ] || continue
        # length() instead of {64}: older mawk has no interval expressions.
        awk -v n="$name" 'NF == 2 && length($1) == 64 && $1 ~ /^[0-9a-f]+$/ && $2 == n { h = $1 } END { if (h) print h }' "$file"
    done | tail -n1
}

sha_of() { sha256sum "$1" 2>/dev/null | awk '{print $1}'; }

if [ "$(uname -m)" != "x86_64" ]; then
    warn "Piper: this installer only knows the x86_64 release (this is $(uname -m)) — skipped; espeak-ng stays the voice."
    exit 0
fi
if ! command -v curl >/dev/null 2>&1; then
    warn "Piper: curl is missing — skipped (sudo apt-get install curl, then re-run $0)."
    exit 0
fi

TMP=$(mktemp -d /tmp/bcm-piper.XXXXXX) || { warn "Piper: mktemp failed — skipped."; exit 0; }
chmod 0700 "$TMP"
trap 'rm -rf "$TMP"' EXIT

# fetch_verified <url> <file name> <output path>: download into $TMP, check
# the hash, move into place. Returns 1 (with a warning) on any problem.
fetch_verified() {
    local url=$1 name=$2 out=$3 want got
    want=$(expected_hash "$name")
    if [ -z "$want" ]; then
        warn "Piper: no SHA-256 listed for $name — NOT installed."
        warn "  Add \"<sha256>  $name\" to /etc/bcm/piper.sha256 (instructions in"
        warn "  $SCRIPT_DIR/piper-sha256.txt), then re-run: sudo bash $0"
        return 1
    fi
    if ! curl -fsSL --proto '=https' --tlsv1.2 --retry 2 --max-time 900 -o "$TMP/$name" "$url"; then
        warn "Piper: download of $name failed (no internet?) — re-run $0 later."
        rm -f "$TMP/$name"
        return 1
    fi
    got=$(sha_of "$TMP/$name")
    if [ "$got" != "$want" ]; then
        warn "Piper: SHA-256 of $name does NOT match the list — deleted, NOT installed."
        warn "  expected $want"
        warn "  got      $got"
        rm -f "$TMP/$name"
        return 1
    fi
    mv -f "$TMP/$name" "$out"
}

install -d -m 0755 -o root -g root "$DEST" "$DEST/voices"

# 1. The Piper release (binary, libraries, espeak-ng-data). A stamp holds the
#    tarball's hash: same hash + binary present = already installed.
STAMP="$DEST/.installed-$PIPER_TARBALL.sha256"
WANT_TAR=$(expected_hash "$PIPER_TARBALL")
if [ -n "$WANT_TAR" ] && [ -x "$DEST/piper/piper" ] && [ -f "$STAMP" ] \
        && [ "$(cat "$STAMP" 2>/dev/null)" = "$WANT_TAR" ]; then
    echo "    Piper $PIPER_VERSION: already installed ($DEST/piper/piper)"
elif fetch_verified "$PIPER_URL" "$PIPER_TARBALL" "$TMP/piper.tar.gz.ok"; then
    if tar -tzf "$TMP/piper.tar.gz.ok" | grep -qE '^/|(^|/)\.\.(/|$)'; then
        warn "Piper: the archive contains absolute or '..' paths — refused."
    else
        rm -rf "$TMP/x" && mkdir "$TMP/x"
        if tar --no-same-owner --no-same-permissions -xzf "$TMP/piper.tar.gz.ok" -C "$TMP/x" \
                && [ -x "$TMP/x/piper/piper" ]; then
            chown -R root:root "$TMP/x/piper"
            chmod -R u+rwX,go+rX,go-w "$TMP/x/piper"
            rm -rf "$DEST/piper.old"
            [ -d "$DEST/piper" ] && mv "$DEST/piper" "$DEST/piper.old"
            mv "$TMP/x/piper" "$DEST/piper" && rm -rf "$DEST/piper.old"
            echo "$WANT_TAR" > "$STAMP"
            echo "    Piper $PIPER_VERSION: installed in $DEST/piper"
        else
            warn "Piper: unpacking failed — not installed."
        fi
    fi
fi

# 2. The voice: model + its settings (Piper needs both).
for f in "$VOICE.onnx" "$VOICE.onnx.json"; do
    want=$(expected_hash "$f")
    if [ -n "$want" ] && [ -f "$DEST/voices/$f" ] && [ "$(sha_of "$DEST/voices/$f")" = "$want" ]; then
        echo "    voice $f: already installed"
        continue
    fi
    if fetch_verified "$VOICE_URL/$f" "$f" "$TMP/$f.ok"; then
        install -m 0644 -o root -g root "$TMP/$f.ok" "$DEST/voices/$f"
        echo "    voice $f: installed"
    fi
done

if [ -x "$DEST/piper/piper" ] && [ -f "$DEST/voices/$VOICE.onnx" ] && [ -f "$DEST/voices/$VOICE.onnx.json" ]; then
    echo "    Piper ready: Settings → \"Komunikaty głosowe\" → \"Powiedz test\""
else
    warn "Piper is not complete — BCM speaks with espeak-ng (if installed) until it is."
fi
exit 0
