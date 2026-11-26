#!/usr/bin/env python3
"""Build the Magisk module zip for the car phone's auto power-on.

    python3 tools/car_phone/autoboot/build_module.py [OUT_DIR]

→ OUT_DIR/bcm-autoboot-magisk.zip (default: current directory). Install it
on the phone: Magisk → Moduły → Zainstaluj z pamięci → reboot. Installing
the module writes NOTHING to the boot partition: it only adds the command
``bcm-autoboot`` (= patch_boot.sh) and the two files it injects. The boot
image is changed only by ``su -c bcm-autoboot`` — after ``--dry-run``.
docs/PRZYGOTOWANIE_TELEFONU.md §16.1.

Standard library only (runs on the M910q without extra packages). The zip
is reproducible: fixed timestamps and order.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE_ID = "bcm_autoboot"
VERSION = "1.0.0"
VERSION_CODE = 1
ZIP_NAME = "bcm-autoboot-magisk.zip"
_DATE = (2026, 1, 1, 0, 0, 0)

# The official Magisk module installer stub (Magisk ≥ 20.4).
UPDATE_BINARY = """#!/sbin/sh
umask 022
ui_print() { echo "$1"; }
require_new_magisk() {
  ui_print "*******************************"
  ui_print " Please install Magisk v20.4+! "
  ui_print "*******************************"
  exit 1
}
OUTFD=$2
ZIPFILE=$3
mount /data 2>/dev/null
[ -f /data/adb/magisk/util_functions.sh ] || require_new_magisk
. /data/adb/magisk/util_functions.sh
[ $MAGISK_VER_CODE -lt 20400 ] && require_new_magisk
install_module
exit 0
"""

MODULE_PROP = f"""id={MODULE_ID}
name=BCM autostart po podaniu zasilania
version={VERSION}
versionCode={VERSION_CODE}
author=Alfa156-headunit
description=Polecenie bcm-autoboot: telefon w aucie sam włącza się po podaniu zasilania (≥ 5 % baterii). Instalacja modułu NIE zmienia boot — zrób: su -c "bcm-autoboot --dry-run", potem su -c bcm-autoboot.
"""

CUSTOMIZE = """# Magisk runs this during installation. Nothing is flashed here on
# purpose: the boot image is changed only by an explicit `bcm-autoboot`.
ui_print "- BCM autostart: dodaję polecenie bcm-autoboot"
set_perm_recursive $MODPATH 0 0 0755 0644
set_perm $MODPATH/patch_boot.sh 0 0 0755
set_perm $MODPATH/bcm_autoboot.sh 0 0 0755
set_perm $MODPATH/system/bin/bcm-autoboot 0 2000 0755
ui_print "- Po restarcie, w Termuxie:"
ui_print "    su -c \\"bcm-autoboot --dry-run\\""
ui_print "    su -c bcm-autoboot"
ui_print "- Kopia boot trafi do /sdcard/Download — przenies ja na komputer."
"""

WRAPPER = f"""#!/system/bin/sh
# bcm-autoboot — the BCM Magisk module's command (patch_boot.sh).
export BCM_AUTOBOOT_FILES=/data/adb/modules/{MODULE_ID}
exec /system/bin/sh /data/adb/modules/{MODULE_ID}/patch_boot.sh "$@"
"""

UNINSTALL = """# Removing the module does NOT undo a patched boot image: restore the
# backup first (su -c "bcm-autoboot --restore <kopia>") or flash it in TWRP.
"""


def entries() -> list[tuple[str, bytes, int]]:
    """(path in zip, content, unix mode) in a fixed order."""
    files = [
        ("META-INF/com/google/android/update-binary", UPDATE_BINARY.encode(), 0o755),
        ("META-INF/com/google/android/updater-script", b"#MAGISK\n", 0o644),
        ("module.prop", MODULE_PROP.encode(), 0o644),
        ("customize.sh", CUSTOMIZE.encode(), 0o644),
        ("uninstall.sh", UNINSTALL.encode(), 0o644),
        ("system/bin/bcm-autoboot", WRAPPER.encode(), 0o755),
    ]
    for name, mode in (("patch_boot.sh", 0o755), ("bcm_autoboot.sh", 0o755),
                       ("bcm-autoboot.rc", 0o644)):
        files.append((name, (HERE / name).read_bytes(), mode))
    return files


def build(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / ZIP_NAME
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data, mode in entries():
            info = zipfile.ZipInfo(name, date_time=_DATE)
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return target


if __name__ == "__main__":
    path = build(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd())
    print(path)
