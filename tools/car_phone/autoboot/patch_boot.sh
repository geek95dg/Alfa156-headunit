#!/system/bin/sh
# patch_boot.sh — add bcm-autoboot (turn on when power arrives) to the boot
# image of the rooted car phone (Redmi Note 8 Pro, Magisk).
# Instructions: docs/PRZYGOTOWANIE_TELEFONU.md §16.1.
#
# Run AS ROOT on the phone (Termux):
#   su -c "sh /sdcard/Download/bcm-autoboot/patch_boot.sh --dry-run"
#   su -c "sh /sdcard/Download/bcm-autoboot/patch_boot.sh"
#   su -c "sh /sdcard/Download/bcm-autoboot/patch_boot.sh --restore /sdcard/Download/boot-przed-autoboot-<data>.img"
#
# Safety:
# - before ANY write the current boot partition is copied to
#   /sdcard/Download/boot-przed-autoboot-<data>.img — copy it to the PC too;
#   with it the phone is restored from TWRP (Install → Install Image → boot)
#   or with fastboot (fastboot flash boot <file>);
# - the image is built with Magisk's own magiskboot; the patched file must
#   not exceed the partition; after writing, the partition is read back and
#   compared byte for byte;
# - --dry-run builds the image and stops (nothing is written);
# - re-running is safe: our two overlay files are replaced, nothing else.
# A Magisk "Direct install" update rebuilds boot from the stock backup and
# drops these files — run this script again after updating Magisk.
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
MB=/data/adb/magisk/magiskboot
WORK=/data/local/tmp/bcm-autoboot
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=/sdcard/Download/boot-przed-autoboot-$STAMP.img

die() { echo "BŁĄD: $*" >&2; exit 1; }
say() { echo "==> $*"; }

[ "$(id -u)" = 0 ] || die "uruchom jako root: su -c \"sh $0\""
[ -x "$MB" ] || die "brak $MB — czy Magisk jest zainstalowany?"
for f in bcm-autoboot.rc bcm_autoboot.sh; do
    [ -f "$HERE/$f" ] || die "brak $HERE/$f (skopiuj cały katalog bcm-autoboot)"
done

# The boot partition (A/B devices: the active slot).
SLOT=$(getprop ro.boot.slot_suffix)
BOOT=""
for d in /dev/block/by-name /dev/block/bootdevice/by-name /dev/block/platform/bootdevice/by-name; do
    if [ -e "$d/boot$SLOT" ]; then BOOT=$(readlink -f "$d/boot$SLOT"); break; fi
done
[ -n "$BOOT" ] && [ -b "$BOOT" ] || die "nie znalazłem partycji boot$SLOT"
PART_SIZE=$(blockdev --getsize64 "$BOOT")
say "partycja boot$SLOT: $BOOT ($PART_SIZE B)"

flash() {   # flash IMAGE: write + read back + compare
    img=$1
    size=$(stat -c %s "$img")
    [ "$size" -le "$PART_SIZE" ] || die "obraz ($size B) większy niż partycja ($PART_SIZE B)"
    say "zapisuję $img"
    dd if="$img" of="$BOOT" bs=4096 conv=fsync 2>/dev/null
    sync
    dd if="$BOOT" of="$WORK/verify.img" bs=4096 count=$(( (size + 4095) / 4096 )) 2>/dev/null
    head -c "$size" "$WORK/verify.img" > "$WORK/verify.cut"
    cmp -s "$img" "$WORK/verify.cut" || die "odczyt po zapisie różni się od obrazu — przywróć kopię ($0 --restore <kopia>)"
    rm -f "$WORK/verify.img" "$WORK/verify.cut"
    say "zapis sprawdzony (bajt w bajt)"
}

rm -rf "$WORK"
mkdir -p "$WORK"
chmod 700 "$WORK"

if [ "$1" = "--restore" ]; then
    [ -f "$2" ] || die "podaj plik kopii: $0 --restore /sdcard/Download/boot-przed-autoboot-<data>.img"
    flash "$2"
    say "przywrócono. Uruchom telefon ponownie."
    exit 0
fi

say "kopia obecnego boot → $BACKUP"
dd if="$BOOT" of="$BACKUP" bs=4096 2>/dev/null
sync
[ "$(stat -c %s "$BACKUP")" = "$PART_SIZE" ] || die "kopia ma zły rozmiar — przerywam"

cd "$WORK"
cp "$BACKUP" boot.img
"$MB" unpack boot.img >/dev/null 2>&1 || die "magiskboot nie rozpakował boot.img"
[ -f ramdisk.cpio ] || die "brak ramdisk.cpio w obrazie (nietypowy boot) — przerywam"
"$MB" cpio ramdisk.cpio "exists .backup/.magisk" || die "boot nie jest spatchowany przez Magisk — najpierw Magisk, potem ten skrypt"

"$MB" cpio ramdisk.cpio \
    "mkdir 0700 overlay.d" \
    "mkdir 0700 overlay.d/sbin" \
    "add 0644 overlay.d/bcm-autoboot.rc $HERE/bcm-autoboot.rc" \
    "add 0755 overlay.d/sbin/bcm_autoboot.sh $HERE/bcm_autoboot.sh" \
    || die "nie udało się dodać plików do ramdisku"
"$MB" repack boot.img new-boot.img >/dev/null 2>&1 || die "magiskboot nie spakował obrazu"
say "nowy obraz: $WORK/new-boot.img ($(stat -c %s new-boot.img) B)"

if [ "$1" = "--dry-run" ]; then
    say "--dry-run: nic nie zapisano. Kopia boot: $BACKUP"
    exit 0
fi

flash "$WORK/new-boot.img"
say "gotowe. Kopia sprzed zmiany: $BACKUP — przenieś ją też na komputer."
say "Test: wyłącz telefon, podłącz zasilanie; po animacji baterii (≥ 5 %) sam się uruchomi."
