#!/bin/bash
# BCM v8.5 — system odporny na odcięcie prądu + szybszy start (M910q, x86)
#
# Wariant testowy w aucie nie ma zasilania buforowanego: każde zgaszenie
# silnika to twarde odcięcie prądu w dowolnej chwili. Ten skrypt:
#   - zmniejsza liczbę zapisów na dysk i okno, w którym zmienione dane
#     czekają w RAM-ie (journald w RAM-ie, krótszy writeback, noatime),
#   - każe naprawiać system plików przy starcie zamiast pomijać fsck
#     (fsck.mode=skip + odcięcie prądu = komputer, który kiedyś nie wstanie),
#   - wyłącza to, co spowalnia start albo pisze po dysku w tle — przede
#     wszystkim automatyczne aktualizacje: dpkg przerwany odcięciem prądu
#     potrafi zostawić system, który się nie uruchamia.
#
# Kroki:
#    1. warunki wstępne (root, repo, systemd)
#    2. unity BCM z repo (headunit, watcher, bcm-timesync) + /etc/bcm/bcm.env (0600)
#    3. journald tylko w RAM-ie (Storage=volatile, RuntimeMaxUse=64M)
#    4. sysctl: zmienione dane trafiają na dysk po 5 s zamiast po 30 s
#    5. fstab: noatime dla / (tylko ext4; weryfikacja findmnt, kopia, remount)
#    6. GRUB: zamiast fsck.mode=skip — fsck.repair=yes (kopia, update-grub)
#    7. szybszy start: mask NetworkManager-wait-online, bez apt-daily*
#       i unattended-upgrades, bez cloud-init; snapy tylko raport
#    8. NetworkManager + Bluetooth PAN (internet z telefonu) — tylko raport
#    9. bcm-timesync.timer włączony
#   10. podsumowanie: kopie zapasowe, BIOS, czas startu
#
# Użycie:
#   sudo bash config/scripts/bcm-harden.sh --dry-run   # pokaż zmiany, nic nie zmieniaj
#   sudo bash config/scripts/bcm-harden.sh             # zastosuj
#   sudo bash config/scripts/bcm-harden.sh --no-units  # bez kroku unitów (z setup-x86.sh)
#
# Zmienne środowiska:
#   BCM_DIR=/opt/bcm    katalog repo — źródło unitów (same unity i tak
#                       wskazują /opt/bcm)
#   BCM_COMMIT_SEC=N    dopisz commit=N (1–60 s) do opcji / w fstab;
#                       domyślnie commit= zostaje bez zmian
#
# Idempotentny: drugi przebieg niczego nie zmienia.
#
# Cofnięcie. UWAGA: cleanup-x86.sh to PEŁNA deinstalacja BCM (usuwa wszystkie
# unity bcm-*, kiosk i autologin, konfigurację AP i /opt/bcm/.venv) — przy
# okazji cofa też zmiany tego skryptu. Żeby cofnąć tylko wybrany punkt:
#   journald:     sudo rm /etc/systemd/journald.conf.d/10-bcm-volatile.conf
#                 sudo systemctl restart systemd-journald
#   sysctl:       sudo rm /etc/sysctl.d/90-bcm-powerloss.conf
#                 sudo sysctl -w vm.dirty_expire_centisecs=3000 vm.dirty_writeback_centisecs=500
#                 sudo sysctl --system
#   wait-online:  sudo systemctl unmask NetworkManager-wait-online.service
#   apt:          grep -v '^#' /etc/bcm/.harden-apt-disabled | xargs -r sudo systemctl enable --now
#                 sudo rm /etc/bcm/.harden-apt-disabled
#   cloud-init:   sudo rm /etc/cloud/cloud-init.disabled /etc/bcm/.harden-cloudinit-disabled
#   timesync:     sudo systemctl disable --now bcm-timesync.timer
#   fstab, GRUB:  sudo cp KOPIA ORYGINAŁ (ścieżki kopii są w podsumowaniu),
#                 po GRUB-ie jeszcze sudo update-grub
#   config BCM:   BCM_CONFIG=config/bcm_config_temp.yaml w /etc/bcm/bcm.env
#                 (unit znów startuje ze starego pliku; patrz krok 2)
# apt i cloud-init cleanup-x86.sh włącza z powrotem tylko wtedy, gdy wyłączył
# je ten skrypt (pliki-znaczniki w /etc/bcm); fstab i GRUB zostawia.
#
# --dry-run jest wiarygodny z konstrukcji: każda zmiana stanu systemu idzie
# przez run() / run_quiet() / atomic_replace() (write_file() i install_file()
# korzystają z atomic_replace()), które w trybie próbnym tylko wypisują, co
# by zrobiły. Odczyty (findmnt, systemctl is-enabled, ...) i pliki robocze
# w prywatnym katalogu tymczasowym działają normalnie, więc podgląd różnic
# fstab/GRUB jest prawdziwy. tests/test_scripts.py pilnuje, żeby żadne
# polecenie zmieniające system nie omijało tych funkcji.
set -euo pipefail

BCM_DIR="${BCM_DIR:-/opt/bcm}"
COMMIT_SEC="${BCM_COMMIT_SEC:-}"
DRY_RUN=0
NO_UNITS=0
TOTAL=10

STAMP="$(date +%Y%m%d-%H%M%S)"
WORK_DIR=""
# Ustawiane przez write_file()/install_file(): 1 = plik został (albo w trybie
# próbnym zostałby) zmieniony. Zmienna globalna, a nie kod wyjścia, bo
# funkcja wołana w "if" traci set -e — błąd zapisu nie przerwałby skryptu.
WROTE=0
BACKUPS=()
# 1 = unit przechodzi na bcm_config_test.yaml, a ustawień z auta jeszcze nie
# przeniesiono do config/local.yaml (patrz check_config_migration).
MIGRATION_PENDING=0

ENV_FILE=/etc/bcm/bcm.env
APT_MARKER=/etc/bcm/.harden-apt-disabled
CLOUDINIT_MARKER=/etc/bcm/.harden-cloudinit-disabled
JOURNALD_DROPIN=/etc/systemd/journald.conf.d/10-bcm-volatile.conf
SYSCTL_DROPIN=/etc/sysctl.d/90-bcm-powerloss.conf
APT_UNITS=(apt-daily.timer apt-daily-upgrade.timer unattended-upgrades.service)

if [ -t 1 ]; then
    RED=$'\033[0;31m'
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[1;33m'
    CYAN=$'\033[0;36m'
    NC=$'\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    CYAN=''
    NC=''
fi

step() { printf '\n%s[%s/%s] %s%s\n' "$GREEN" "$1" "$TOTAL" "$2" "$NC"; }
info() { printf '  %s\n' "$*"; }
ok() { printf '  %sOK%s\n' "$GREEN" "$NC"; }
warn() { printf '  %sUWAGA: %s%s\n' "$YELLOW" "$*" "$NC"; }
fail() {
    printf '  %sBŁĄD: %s%s\n' "$RED" "$*" "$NC" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Użycie: sudo bash config/scripts/bcm-harden.sh [--dry-run] [--no-units]

  --dry-run, -n   pokaż każdą zmianę, niczego nie zmieniaj
  --no-units      pomiń odświeżanie unitów BCM (setup-x86.sh instaluje je sam)
  -h, --help      ta pomoc

Zmienne: BCM_DIR (domyślnie /opt/bcm), BCM_COMMIT_SEC (opcjonalnie commit=N dla /).
EOF
}

# ─── Funkcje zmieniające system (jedyne miejsca, patrz nagłówek) ─────────

run() {
    local cmd
    printf -v cmd '%q ' "$@"
    if [ "$DRY_RUN" = 1 ]; then
        printf '  %s[dry-run]%s %s\n' "$CYAN" "$NC" "${cmd% }"
        return 0
    fi
    printf '  $ %s\n' "${cmd% }"
    "$@"
}

# Jak run(), ale bez stdout polecenia (np. sysctl --system wypisuje setki linii).
run_quiet() {
    local cmd
    printf -v cmd '%q ' "$@"
    if [ "$DRY_RUN" = 1 ]; then
        printf '  %s[dry-run]%s %s\n' "$CYAN" "$NC" "${cmd% }"
        return 0
    fi
    printf '  $ %s\n' "${cmd% }"
    "$@" >/dev/null
}

# Podmiana pliku odporna na odcięcie prądu: kopia obok celu (ten sam system
# plików) → fsync → rename → fsync katalogu. Po cięciu w środku zostaje
# stary albo nowy plik, nigdy obcięty. Zawsze root:root.
atomic_replace() {
    local src="$1"
    local dest="$2"
    local mode="$3"
    local dir tmp
    dir="$(dirname "$dest")"
    tmp="$dir/.$(basename "$dest").bcm-new"
    if [ "$DRY_RUN" = 1 ]; then
        printf '  %s[dry-run]%s zapis %s (tryb %s, root:root, atomowo)\n' "$CYAN" "$NC" "$dest" "$mode"
        return 0
    fi
    printf '  $ zapis %s (tryb %s, root:root, atomowo)\n' "$dest" "$mode"
    [ -d "$dir" ] || install -d -m 0755 -o root -g root "$dir"
    install -m "$mode" -o root -g root "$src" "$tmp"
    sync "$tmp" 2>/dev/null || sync
    mv -f "$tmp" "$dest"
    sync "$dir" 2>/dev/null || sync
}

cleanup_work() {
    if [ -n "$WORK_DIR" ] && [ -d "$WORK_DIR" ]; then
        rm -rf -- "$WORK_DIR"
    fi
}

# ─── Pomocnicze (tylko odczyt) ───────────────────────────────────────────

unit_exists() {
    [ -n "$(systemctl list-unit-files --no-legend --no-pager "$1" 2>/dev/null)" ]
}

# Przejście unitu z bcm_config_temp.yaml na bcm_config_test.yaml (P1).
# Ustawienia z auta (karta USB audio, telefon BT, ustawienia UI) są dziś
# tylko w temp; dopóki tools/migrate_local_config.py nie przeniesie ich do
# config/local.yaml, BCM wstałby po podmianie unitu bez nich. Nic nie
# ginie (temp zostaje), ale bez ostrzeżenia nikt by tego nie zauważył.
# Tylko odczyt; z bcm.env czytamy wyłącznie, czy jest w nim BCM_CONFIG
# ze starym plikiem (grep -q: treść nigdy nie trafia na ekran).
check_config_migration() {
    local unit=/etc/systemd/system/bcm-headunit.service
    local py
    [ -f "$BCM_DIR/config/bcm_config_temp.yaml" ] || return 0
    [ ! -e "$BCM_DIR/config/local.yaml" ] || return 0
    [ -f "$unit" ] || return 0
    grep -q 'bcm_config_temp\.yaml' "$unit" || return 0
    # Świadomy powrót do starego pliku przez bcm.env — nie ma czego migrować.
    if [ -f "$ENV_FILE" ] && grep -Eq '^[[:space:]]*BCM_CONFIG=.*bcm_config_temp\.yaml' "$ENV_FILE" 2>/dev/null; then
        return 0
    fi
    MIGRATION_PENDING=1
    py="$BCM_DIR/.venv/bin/python"
    [ -x "$py" ] || py="$BCM_DIR/venv/bin/python"
    [ -x "$py" ] || py=python3
    warn "zainstalowany bcm-headunit.service startuje z config/bcm_config_temp.yaml, a config/local.yaml jeszcze nie ma"
    warn "po podmianie unitu BCM wstanie z config/bcm_config_test.yaml BEZ ustawień z auta (karta USB, telefon BT, UI)"
    info "przenieś je PRZED następnym startem BCM — najpierw podgląd (nic nie zapisuje):"
    info "  cd $BCM_DIR && sudo $py tools/migrate_local_config.py --source config/bcm_config_temp.yaml --base config/bcm_config_test.yaml --out config/local.yaml"
    info "potem to samo polecenie z --write"
    info "albo zostań przy starym pliku: dopisz BCM_CONFIG=config/bcm_config_temp.yaml do $ENV_FILE"
    info "(bcm_config_temp.yaml zostaje na miejscu — nic nie ginie)"
}

# 0, gdy dest to zwykły plik o tej samej treści co src, z trybem mode i
# właścicielem root:root — wtedy nie ma czego zapisywać.
same_file() {
    local src="$1"
    local dest="$2"
    local mode="$3"
    if [ ! -f "$dest" ] || [ -L "$dest" ]; then
        return 1
    fi
    cmp -s "$src" "$dest" || return 1
    [ "$(stat -c '%a %u %g' "$dest" 2>/dev/null || true)" = "${mode#0} 0 0" ]
}

# Różnice pokazujemy tylko w trybie próbnym — przy prawdziwym przebiegu
# zmienione unity zalałyby ekran. Nigdy nie wołać dla plików z sekretami.
show_diff() {
    [ "$DRY_RUN" = 1 ] || return 0
    diff -u "$1" "$2" | sed 's/^/      /' || true
}

# Zainstaluj plik z repo, jeśli różni się od zainstalowanego (treść/tryb).
install_file() {
    local src="$1"
    local dest="$2"
    local mode="$3"
    WROTE=0
    if [ ! -f "$src" ]; then
        warn "brak $src w repo — pomijam $dest"
        return 0
    fi
    if same_file "$src" "$dest" "$mode"; then
        info "bez zmian: $dest"
        return 0
    fi
    if [ -f "$dest" ]; then
        show_diff "$dest" "$src"
    fi
    atomic_replace "$src" "$dest" "$mode"
    WROTE=1
}

# Zapisz treść ze stdin do dest, jeśli się różni.
write_file() {
    local dest="$1"
    local mode="$2"
    local tmp
    WROTE=0
    tmp="$(mktemp "$WORK_DIR/new.XXXXXX")"
    cat >"$tmp"
    if same_file "$tmp" "$dest" "$mode"; then
        info "bez zmian: $dest"
        return 0
    fi
    if [ "$DRY_RUN" = 1 ]; then
        if [ -f "$dest" ]; then
            show_diff "$dest" "$tmp"
        else
            sed 's/^/      | /' "$tmp"
        fi
    fi
    atomic_replace "$tmp" "$dest" "$mode"
    WROTE=1
}

# Plik-znacznik = lista jednostek, które wyłączył TEN skrypt (cleanup-x86.sh
# włącza z powrotem tylko je). Nowe nazwy dopisujemy do istniejących.
update_marker() {
    local marker="$1"
    shift
    local content name
    local -a names=()
    if [ -f "$marker" ]; then
        while read -r name; do
            case "$name" in
                '' | '#'*) continue ;;
            esac
            names+=("$name")
        done <"$marker"
    fi
    names+=("$@")
    content="$WORK_DIR/marker.content"
    {
        echo "# bcm-harden.sh: jednostki wyłączone przez ten skrypt; cleanup-x86.sh włączy je z powrotem."
        printf '%s\n' "${names[@]}" | sort -u
    } >"$content"
    write_file "$marker" 0644 <"$content"
}

record_backup() { BACKUPS+=("$1"); }

# Kopia zapasowa pliku systemowego tuż przed jego podmianą. sync (fsync
# kopii i katalogu) PRZED atomic_replace: inaczej po cięciu prądu zaraz po
# podmianie nowy plik mógłby już być na dysku, a kopia — jedyna droga
# powrotu, wypisana w podsumowaniu — pusta albo obcięta (ext4 opóźnia
# przydział bloków). cp -a, bo wołający odrzuca dowiązania symboliczne.
backup_file() {
    local src="$1"
    local backup="$2"
    run cp -a "$src" "$backup"
    run sync "$backup" "$(dirname "$backup")" || run sync
    record_backup "$backup"
}

# Czysta funkcja: tryb dla podmienianego pliku systemowego (fstab, GRUB) —
# taki jak miał, ale nigdy szerszy niż 0644. update-grub "source"-uje
# /etc/default/grub jako root: plik zapisywalny dla grupy/innych to droga
# do roota, a bity wykonania i specjalne nie mają tu sensu. Nieczytelny
# tryb → 0644 (domyślny dla obu plików).
cap_mode() {
    local mode="$1"
    case "$mode" in
        '' | *[!0-7]*) mode=644 ;;
    esac
    printf '%04o\n' "$((8#$mode & 8#0644))"
}

# Czysta funkcja: opcje montowania / po zmianie. Usuwa relatime/strictatime/
# atime (kłócą się z noatime), dodaje noatime; commit=N tylko, gdy podano
# drugi argument (inaczej istniejące commit= zostaje, jak było).
fstab_new_options() {
    local opts="$1"
    local commit="$2"
    local o
    local have_noatime=0
    local have_commit=0
    local -a list=()
    local -a out=()
    IFS=, read -r -a list <<<"$opts"
    for o in "${list[@]}"; do
        case "$o" in
            '') ;;
            noatime)
                have_noatime=1
                out+=("$o")
                ;;
            relatime | strictatime | atime) ;;
            commit=*)
                if [ -z "$commit" ]; then
                    out+=("$o")
                elif [ "$have_commit" = 0 ]; then
                    out+=("commit=$commit")
                    have_commit=1
                fi
                ;;
            *) out+=("$o") ;;
        esac
    done
    if [ "$have_noatime" = 0 ]; then
        out+=(noatime)
    fi
    if [ -n "$commit" ] && [ "$have_commit" = 0 ]; then
        out+=("commit=$commit")
    fi
    local IFS=,
    printf '%s\n' "${out[*]}"
}

# Czysta funkcja: linia GRUB_CMDLINE_LINUX_DEFAULT=... po zmianie — bez
# fsck.mode=skip, z fsck.repair=yes (istniejące fsck.repair=* → yes).
# Operuje na całych słowach, więc nie trafi w podobne opcje. Zwraca 1, gdy
# linii nie da się bezpiecznie rozebrać — wtedy plik zostaje nietknięty.
grub_new_line() {
    local line="$1"
    local value q inner t
    local have_repair=0
    local -a toks=()
    local -a out=()
    value="${line#GRUB_CMDLINE_LINUX_DEFAULT=}"
    [ "$value" != "$line" ] || return 1
    q="${value:0:1}"
    if [ "$q" != '"' ] && [ "$q" != "'" ]; then
        return 1
    fi
    [ "${#value}" -ge 2 ] || return 1
    [ "${value: -1}" = "$q" ] || return 1
    inner="${value:1:${#value}-2}"
    case "$inner" in
        *"$q"*) return 1 ;;
    esac
    read -r -a toks <<<"$inner"
    for t in "${toks[@]}"; do
        case "$t" in
            fsck.mode=skip) ;;
            fsck.repair=*)
                if [ "$have_repair" = 0 ]; then
                    out+=(fsck.repair=yes)
                    have_repair=1
                fi
                ;;
            *) out+=("$t") ;;
        esac
    done
    if [ "$have_repair" = 0 ]; then
        out+=(fsck.repair=yes)
    fi
    printf 'GRUB_CMDLINE_LINUX_DEFAULT=%s%s%s\n' "$q" "${out[*]}" "$q"
}

parse_args() {
    local arg
    for arg in "$@"; do
        case "$arg" in
            --dry-run | -n) DRY_RUN=1 ;;
            --no-units) NO_UNITS=1 ;;
            -h | --help)
                usage
                exit 0
                ;;
            *)
                printf 'Nieznana opcja: %s\n\n' "$arg" >&2
                usage >&2
                exit 2
                ;;
        esac
    done
}

# ─── Kroki ───────────────────────────────────────────────────────────────

step_preconditions() {
    step 1 "Warunki wstępne..."
    if [ "$DRY_RUN" = 1 ]; then
        info "TRYB PRÓBNY (--dry-run): niczego nie zmieniam, tylko pokazuję."
    fi
    if [ "$(id -u)" -ne 0 ]; then
        if [ "$DRY_RUN" = 1 ]; then
            warn "bez roota część odczytów może być niepełna (np. /etc/bcm)"
        else
            fail "Uruchom przez sudo: sudo bash $0"
        fi
    fi
    case "$BCM_DIR" in
        /*) ;;
        *) fail "BCM_DIR musi być ścieżką bezwzględną (jest: $BCM_DIR)" ;;
    esac
    if [ ! -f "$BCM_DIR/main.py" ]; then
        fail "Nie znaleziono $BCM_DIR/main.py — ustaw BCM_DIR na katalog repo"
    fi
    if [ "$BCM_DIR" != /opt/bcm ]; then
        warn "unity BCM mają na sztywno /opt/bcm (WorkingDirectory); BCM_DIR=$BCM_DIR to tylko źródło plików"
    fi
    if ! command -v systemctl >/dev/null 2>&1; then
        fail "Brak systemctl — ten skrypt jest dla systemu z systemd"
    fi
    if [ -n "$COMMIT_SEC" ]; then
        case "$COMMIT_SEC" in
            *[!0-9]*) fail "BCM_COMMIT_SEC musi być liczbą sekund 1-60 (jest: $COMMIT_SEC)" ;;
        esac
        COMMIT_SEC=$((10#$COMMIT_SEC))
        if [ "$COMMIT_SEC" -lt 1 ] || [ "$COMMIT_SEC" -gt 60 ]; then
            fail "BCM_COMMIT_SEC musi być w zakresie 1-60 (jest: $COMMIT_SEC)"
        fi
    fi
    if [ "$(uname -m)" != x86_64 ]; then
        warn "architektura $(uname -m) — skrypt jest pisany pod M910q (x86_64)"
    fi
    info "BCM_DIR:  $BCM_DIR"
    info "jądro:    $(uname -r)"
    if [ "$NO_UNITS" = 1 ]; then
        info "--no-units: unity instaluje wołający"
    fi
    # Dwa równoległe przebiegi (np. setup-x86.sh i ręczny) pisałyby te same pliki.
    if [ "$DRY_RUN" = 0 ] && command -v flock >/dev/null 2>&1; then
        exec 9>/run/bcm-harden.lock
        flock -n 9 || fail "bcm-harden.sh już działa (blokada /run/bcm-harden.lock)"
    fi
    ok
}

step_units_and_env() {
    step 2 "Unity BCM z repo + /etc/bcm/bcm.env..."
    local changed=0
    local perms dir_perms dir_owner dir_mode
    local sd="$BCM_DIR/config/systemd"
    if [ "$NO_UNITS" = 1 ]; then
        info "pomijam unity (--no-units)"
    else
        # Przed podmianą: czy stary unit (bcm_config_temp.yaml) nie zostawi
        # BCM bez ustawień z auta. Tylko ostrzeżenie — podmiana i tak jest
        # bezpieczna, a powrót to jedna linia w bcm.env.
        check_config_migration
        # Nazwa bcm-headunit.service jak w setup-x86.sh — watcher startuje
        # usługę po tej nazwie (--service bcm-headunit.service).
        install_file "$sd/bcm-headunit-x86.service" /etc/systemd/system/bcm-headunit.service 0644
        changed=$((changed + WROTE))
        install_file "$sd/bcm-ignition-watcher.service" /etc/systemd/system/bcm-ignition-watcher.service 0644
        changed=$((changed + WROTE))
        install_file "$sd/bcm-timesync.service" /etc/systemd/system/bcm-timesync.service 0644
        changed=$((changed + WROTE))
        install_file "$sd/bcm-timesync.timer" /etc/systemd/system/bcm-timesync.timer 0644
        changed=$((changed + WROTE))
        install_file "$BCM_DIR/config/scripts/bcm-timesync.sh" /usr/local/bin/bcm-timesync.sh 0755
        changed=$((changed + WROTE))
        if [ "$changed" -gt 0 ]; then
            run systemctl daemon-reload
            # Bez restartu tutaj: zatrzymałby działający headunit. Nowe unity
            # przejmą się przy następnym starcie usług.
            info "nowe unity zadziałają po: sudo systemctl restart bcm-ignition-watcher (albo po restarcie)"
        fi
    fi

    # Sekrety (klucze API, hasła). Treści NIGDY nie nadpisujemy ani nie
    # wypisujemy; pilnujemy tylko istnienia szkieletu i praw.
    if [ -L /etc/bcm ] || { [ -e /etc/bcm ] && [ ! -d /etc/bcm ]; }; then
        warn "/etc/bcm nie jest zwykłym katalogiem (dowiązanie albo plik) — nie ruszam $ENV_FILE, sprawdź ręcznie"
        return 0
    fi
    if [ ! -d /etc/bcm ]; then
        run install -d -m 0700 -o root -g root /etc/bcm
    else
        # Kto może pisać do katalogu, ten podmieni bcm.env (rename), a
        # systemd wczyta go jako środowisko dwóch usług roota — LD_PRELOAD
        # albo PYTHONPATH to wtedy kod uruchomiony jako root. Prawa 600
        # samego pliku nic wtedy nie dają. Prawa odczytu zostają: w /etc/bcm
        # jest też lte.conf.
        dir_perms="$(stat -c '%u %a' /etc/bcm 2>/dev/null || true)"
        dir_owner="${dir_perms%% *}"
        dir_mode="${dir_perms#* }"
        case "$dir_owner:$dir_mode" in
            :* | *: | *[!0-9:]*)
                warn "nie umiem odczytać właściciela/praw /etc/bcm — sprawdź ręcznie: ls -ld /etc/bcm"
                ;;
            *)
                if [ "$dir_owner" != 0 ]; then
                    warn "/etc/bcm nie należy do roota (uid $dir_owner) — poprawiam"
                    run chown root:root /etc/bcm
                fi
                # Tryb ósemkowy z cyframi 0-7 (stat %a), więc 8#... jest bezpieczne.
                case "$dir_mode" in
                    *[!0-7]*)
                        warn "nietypowe prawa /etc/bcm ('$dir_mode') — sprawdź ręcznie: ls -ld /etc/bcm"
                        ;;
                    *)
                        if [ "$((8#$dir_mode & 8#022))" -ne 0 ]; then
                            warn "/etc/bcm jest zapisywalny dla grupy/innych (tryb $dir_mode) — zabieram prawo zapisu"
                            run chmod go-w /etc/bcm
                        fi
                        ;;
                esac
                ;;
        esac
    fi
    if [ -L "$ENV_FILE" ]; then
        warn "$ENV_FILE to dowiązanie symboliczne — nie zmieniam praw, sprawdź ręcznie"
    elif [ -f "$ENV_FILE" ]; then
        info "$ENV_FILE istnieje — treści nie ruszam"
    elif [ -f "$BCM_DIR/config/bcm.env.example" ]; then
        atomic_replace "$BCM_DIR/config/bcm.env.example" "$ENV_FILE" 0600
        info "szkielet $ENV_FILE z config/bcm.env.example — wpisz klucze: sudo nano $ENV_FILE"
    else
        warn "brak config/bcm.env.example — $ENV_FILE nie został utworzony"
    fi
    # Zawsze 600 root:root: czyta go tylko systemd (EnvironmentFile) jako root.
    if [ -f "$ENV_FILE" ] && [ ! -L "$ENV_FILE" ]; then
        perms="$(stat -c '%a %u %g' "$ENV_FILE" 2>/dev/null || echo '?')"
        if [ "$perms" = "600 0 0" ]; then
            info "prawa $ENV_FILE: 600 root:root"
        else
            run chown root:root "$ENV_FILE"
            run chmod 600 "$ENV_FILE"
        fi
    fi
    ok
}

step_journald() {
    step 3 "journald tylko w RAM-ie (Storage=volatile)..."
    local size
    write_file "$JOURNALD_DROPIN" 0644 <<'EOF'
# BCM (bcm-harden.sh): dziennik systemowy tylko w RAM-ie (/run/log/journal).
# Bez zasilania buforowanego każde zgaszenie silnika to odcięcie prądu:
# dziennik na dysku to ciągłe zapisy i pliki psute przy każdym cięciu.
# Cena: logi z poprzedniego uruchomienia giną. Na czas diagnozy usuń ten
# plik i zrestartuj systemd-journald.
[Journal]
Storage=volatile
RuntimeMaxUse=64M
RuntimeMaxFileSize=8M
EOF
    if [ "$WROTE" = 1 ]; then
        run systemctl restart systemd-journald \
            || warn "restart systemd-journald nie powiódł się — zmiana zadziała po ponownym uruchomieniu"
    fi
    if [ -d /var/log/journal ]; then
        size="$(du -sh /var/log/journal 2>/dev/null | cut -f1 || true)"
        info "stare logi z dysku zostają w /var/log/journal (${size:-?}); journald już do nich nie dopisuje"
    fi
    ok
}

step_sysctl() {
    step 4 "sysctl: krótsze okno niezapisanych danych..."
    local cur_expire cur_writeback
    write_file "$SYSCTL_DROPIN" 0644 <<'EOF'
# BCM (bcm-harden.sh): mniejsze okno strat przy odcięciu prądu.
# Domyślnie jądro trzyma zmienione dane w RAM-ie do 30 s (3000) i budzi
# zapis co 5 s (500). Tu: dane starsze niż 5 s idą na dysk, sprawdzane co 1 s.
vm.dirty_expire_centisecs = 500
vm.dirty_writeback_centisecs = 100
EOF
    cur_expire="$(cat /proc/sys/vm/dirty_expire_centisecs 2>/dev/null || echo '?')"
    cur_writeback="$(cat /proc/sys/vm/dirty_writeback_centisecs 2>/dev/null || echo '?')"
    if [ "$WROTE" = 1 ] || [ "$cur_expire" != 500 ] || [ "$cur_writeback" != 100 ]; then
        run_quiet sysctl --system \
            || warn "sysctl --system zgłosił błąd (może z innego pliku) — sprawdź: sudo sysctl --system"
    fi
    info "było: dirty_expire_centisecs=$cur_expire, dirty_writeback_centisecs=$cur_writeback (cel: 500 / 100)"
    ok
}

step_fstab() {
    step 5 "fstab: noatime dla / (ext4)..."
    local fstab=/etc/fstab
    local live_fs count lineno fstype opts passno new_opts cand verify mode
    local backup=""
    local live_opts
    local remount="remount,noatime"
    # Dowiązanie: stat -c '%a' podałby 777 (tryb linku, nie celu), a
    # podmiana i tak zastąpiłaby link zwykłym plikiem — nie zgadujemy.
    if [ -L "$fstab" ]; then
        warn "$fstab to dowiązanie symboliczne — nie zmieniam, popraw ręcznie (noatime dla /)"
        return 0
    fi
    if [ ! -f "$fstab" ]; then
        warn "brak $fstab — pomijam"
        return 0
    fi
    if ! command -v findmnt >/dev/null 2>&1; then
        warn "brak findmnt (util-linux) — bez weryfikacji nie zmieniam fstab"
        return 0
    fi
    live_fs="$(findmnt -no FSTYPE / 2>/dev/null || true)"
    # Tylko niezakomentowane wpisy z punktem montowania dokładnie "/".
    count="$(awk '$1 !~ /^#/ && $2 == "/" {n++} END {print n + 0}' "$fstab")"
    if [ "$count" != 1 ]; then
        warn "w $fstab jest $count wpisów dla / (oczekiwany 1) — nie zgaduję, pomijam"
        return 0
    fi
    lineno="$(awk '$1 !~ /^#/ && $2 == "/" {print NR; exit}' "$fstab")"
    fstype="$(awk -v n="$lineno" 'NR == n {print $3}' "$fstab")"
    opts="$(awk -v n="$lineno" 'NR == n {print $4}' "$fstab")"
    passno="$(awk -v n="$lineno" 'NR == n {print $6}' "$fstab")"
    if [ "$fstype" != ext4 ] || [ "$live_fs" != ext4 ]; then
        info "/ to '${fstype:-?}' w fstab (zamontowane: '${live_fs:-?}'), nie ext4 — pomijam"
        return 0
    fi
    case "$opts" in
        '') opts=defaults ;;
        *[!A-Za-z0-9_=,.:+/-]*)
            warn "nietypowe opcje montowania / ('$opts') — nie zmieniam fstab"
            return 0
            ;;
    esac
    if [ "${passno:-0}" = 0 ]; then
        warn "6. pole fstab dla / to 0 — / może nie być sprawdzany przy starcie (fsck.repair=yes nic wtedy nie da); zalecane 1"
    fi

    new_opts="$(fstab_new_options "$opts" "$COMMIT_SEC")"
    if [ "$new_opts" = "$opts" ]; then
        info "fstab: / ma już '$opts' — bez zmian"
    else
        info "fstab: opcje / '$opts' -> '$new_opts'"
        cand="$WORK_DIR/fstab.new"
        # Zmieniamy tylko 4. pole jednej linii; reszta pliku bajt w bajt.
        NEW_OPTS="$new_opts" awk -v n="$lineno" \
            'BEGIN {OFS = "\t"} NR == n {$4 = ENVIRON["NEW_OPTS"]} {print}' "$fstab" >"$cand"
        if [ "$(awk 'END {print NR}' "$fstab")" != "$(awk 'END {print NR}' "$cand")" ]; then
            warn "nowy fstab ma inną liczbę linii niż stary — przerywam ten krok"
            return 0
        fi
        diff -u "$fstab" "$cand" | sed 's/^/      /' || true
        # Nieudany fstab = system, który nie wstaje. Bez pozytywnej
        # weryfikacji nie podmieniamy.
        if ! verify="$(findmnt --verify --tab-file "$cand" 2>&1)"; then
            warn "findmnt --verify odrzucił nowy fstab — nie zmieniam:"
            printf '%s\n' "$verify" | sed 's/^/      /'
            if ! findmnt --verify --tab-file "$fstab" >/dev/null 2>&1; then
                warn "obecny $fstab też nie przechodzi weryfikacji — popraw go ręcznie (sudo findmnt --verify)"
            fi
            return 0
        fi
        mode="$(cap_mode "$(stat -c '%a' "$fstab" 2>/dev/null || true)")"
        backup="/etc/fstab.bcm-$STAMP.bak"
        backup_file "$fstab" "$backup"
        atomic_replace "$cand" "$fstab" "$mode"
        run systemctl daemon-reload
    fi

    if [ -n "$COMMIT_SEC" ]; then
        remount="$remount,commit=$COMMIT_SEC"
    fi
    live_opts="$(findmnt -no OPTIONS / 2>/dev/null || true)"
    case ",$live_opts," in
        *,noatime,*)
            if [ -z "$COMMIT_SEC" ]; then
                info "/ zamontowane z noatime — OK"
                ok
                return 0
            fi
            case ",$live_opts," in
                *",commit=$COMMIT_SEC,"*)
                    info "/ zamontowane z noatime,commit=$COMMIT_SEC — OK"
                    ok
                    return 0
                    ;;
            esac
            ;;
    esac
    run mount -o "$remount" / \
        || warn "remount / nie powiódł się — noatime zadziała po ponownym uruchomieniu"
    ok
}

step_grub() {
    step 6 "GRUB: fsck.repair=yes zamiast fsck.mode=skip..."
    local grub=/etc/default/grub
    local count lineno line new_line cand mode f
    local backup=""
    local other_skip=""
    local regen=0
    # Jak w fstab: tryb linku to 777, a podmiana zastąpiłaby link plikiem.
    if [ -L "$grub" ]; then
        warn "$grub to dowiązanie symboliczne — nie zmieniam"
        warn "popraw ręcznie: usuń fsck.mode=skip, dodaj fsck.repair=yes, potem sudo update-grub"
        return 0
    fi
    if [ ! -f "$grub" ]; then
        info "brak $grub — pomijam (system bez GRUB-a?)"
        return 0
    fi
    count="$(awk '/^GRUB_CMDLINE_LINUX_DEFAULT=/ {n++} END {print n + 0}' "$grub")"
    if [ "$count" != 1 ]; then
        warn "w $grub jest $count linii GRUB_CMDLINE_LINUX_DEFAULT= (oczekiwana 1) — popraw ręcznie"
        return 0
    fi
    lineno="$(awk '/^GRUB_CMDLINE_LINUX_DEFAULT=/ {print NR; exit}' "$grub")"
    line="$(awk -v n="$lineno" 'NR == n {print; exit}' "$grub")"
    if ! new_line="$(grub_new_line "$line")"; then
        warn "nie umiem bezpiecznie rozebrać: $line"
        warn "popraw ręcznie: usuń fsck.mode=skip, dodaj fsck.repair=yes, potem sudo update-grub"
        return 0
    fi

    if [ "$new_line" = "$line" ]; then
        info "GRUB: już jest fsck.repair=yes, bez fsck.mode=skip"
    else
        cand="$WORK_DIR/grub.new"
        # Podmieniamy wyłącznie tę jedną linię. ENVIRON zamiast awk -v, bo
        # -v interpretowałoby odwrotne ukośniki w treści linii.
        NEW_LINE="$new_line" awk -v n="$lineno" \
            'NR == n {print ENVIRON["NEW_LINE"]; next} {print}' "$grub" >"$cand"
        diff -u "$grub" "$cand" | sed 's/^/      /' || true
        mode="$(cap_mode "$(stat -c '%a' "$grub" 2>/dev/null || true)")"
        backup="/etc/default/grub.bcm-$STAMP.bak"
        backup_file "$grub" "$backup"
        atomic_replace "$cand" "$grub" "$mode"
        regen=1
    fi

    # Ta sama opcja gdzie indziej unieważnia zmianę — tylko raport.
    if grep -Eq '^GRUB_CMDLINE_LINUX=.*fsck\.mode=skip' "$grub"; then
        other_skip="$grub (GRUB_CMDLINE_LINUX)"
    fi
    for f in /etc/default/grub.d/*.cfg; do
        if [ -f "$f" ] && grep -q 'fsck\.mode=skip' "$f"; then
            other_skip="$other_skip $f"
        fi
    done
    if [ -n "$other_skip" ]; then
        warn "fsck.mode=skip jest też w: $other_skip — usuń ręcznie, inaczej fsck dalej będzie pomijany"
    elif [ "$regen" = 0 ] && [ -r /boot/grub/grub.cfg ] && grep -q 'fsck\.mode=skip' /boot/grub/grub.cfg; then
        # grub.cfg z czasów przed zmianą (np. po nieudanym update-grub).
        info "/boot/grub/grub.cfg wciąż ma fsck.mode=skip — generuję ponownie"
        regen=1
    fi

    if [ "$regen" = 1 ]; then
        if command -v update-grub >/dev/null 2>&1; then
            run update-grub \
                || warn "update-grub nie powiódł się; przywrócenie: sudo cp ${backup:-KOPIA} $grub && sudo update-grub"
        elif command -v grub-mkconfig >/dev/null 2>&1; then
            run grub-mkconfig -o /boot/grub/grub.cfg \
                || warn "grub-mkconfig nie powiódł się; przywrócenie: sudo cp ${backup:-KOPIA} $grub"
        else
            warn "brak update-grub i grub-mkconfig — wygeneruj grub.cfg ręcznie"
        fi
    fi
    case " $(cat /proc/cmdline 2>/dev/null || true) " in
        *" fsck.mode=skip "*)
            info "obecny start ma jeszcze fsck.mode=skip — nowe opcje zadziałają po ponownym uruchomieniu"
            ;;
    esac
    ok
}

step_boot() {
    step 7 "Szybszy start: wait-online, apt w tle, cloud-init, snapy..."
    local state u snaps
    local -a to_disable=()

    # NetworkManager-wait-online czeka przy starcie na sieć, której w aucie
    # zwykle nie ma. Nic w BCM jej nie potrzebuje: bcm-timesync ma własne
    # opóźnienie i ponawia co godzinę.
    state="$(systemctl is-enabled NetworkManager-wait-online.service 2>/dev/null || true)"
    if [ "$state" = masked ]; then
        info "NetworkManager-wait-online.service już zamaskowany"
    elif unit_exists NetworkManager-wait-online.service; then
        run systemctl mask NetworkManager-wait-online.service \
            || warn "nie udało się zamaskować NetworkManager-wait-online.service"
    else
        info "brak NetworkManager-wait-online.service — pomijam"
    fi

    # Automatyczne aktualizacje: dpkg przerwany odcięciem prądu w trakcie
    # jazdy = ryzyko systemu, który nie wstanie. Aktualizacje tylko ręcznie,
    # na postoju, z pewnym zasilaniem. Znacznik zapisujemy PRZED wyłączeniem,
    # żeby cięcie w środku nie zostawiło wyłączonej usługi bez śladu.
    for u in "${APT_UNITS[@]}"; do
        if ! unit_exists "$u"; then
            info "$u: brak — pomijam"
            continue
        fi
        state="$(systemctl is-enabled "$u" 2>/dev/null || true)"
        case "$state" in
            enabled | enabled-runtime) to_disable+=("$u") ;;
            *)
                info "$u: już wyłączony ($state)"
                if systemctl is-active --quiet "$u" 2>/dev/null; then
                    run systemctl stop "$u" || warn "nie udało się zatrzymać $u"
                fi
                ;;
        esac
    done
    if [ "${#to_disable[@]}" -gt 0 ]; then
        update_marker "$APT_MARKER" "${to_disable[@]}"
        for u in "${to_disable[@]}"; do
            run systemctl disable --now "$u" || warn "nie udało się wyłączyć $u"
        done
    fi

    # cloud-init nie ma tu nic do roboty, a przy każdym starcie szuka źródeł danych.
    if [ -d /etc/cloud ]; then
        if [ -e /etc/cloud/cloud-init.disabled ]; then
            info "cloud-init już wyłączony (/etc/cloud/cloud-init.disabled)"
        else
            write_file "$CLOUDINIT_MARKER" 0644 <<'EOF'
# bcm-harden.sh utworzył /etc/cloud/cloud-init.disabled; cleanup-x86.sh go usunie.
EOF
            run touch /etc/cloud/cloud-init.disabled
        fi
    else
        info "cloud-init nie jest zainstalowany — OK"
    fi

    # Snapy: tylko raport. Jeśli chromium (kiosk) jest snapem, usunięcie
    # snapd zabrałoby przeglądarkę.
    if command -v snap >/dev/null 2>&1; then
        snaps="$(snap list 2>/dev/null | awk 'NR > 1 {printf "%s ", $1}' || true)"
        info "snapy: ${snaps:-brak}"
        if snap list chromium >/dev/null 2>&1; then
            warn "chromium jest snapem — snapd zostaje (kiosk go potrzebuje); snapd wydłuża start, rozważ chromium z deb"
        fi
    else
        info "snapd nie jest zainstalowany — OK"
    fi
    ok
}

step_nm_bluetooth() {
    step 8 "NetworkManager + Bluetooth PAN (internet z telefonu) — tylko raport..."
    local plugin f
    local hits=""
    if systemctl is-active --quiet NetworkManager 2>/dev/null; then
        info "NetworkManager: działa"
    else
        warn "NetworkManager nie działa — internet z telefonu (BT PAN) go wymaga"
    fi
    plugin="$(find /usr/lib -name 'libnm-device-plugin-bluetooth.so' -print -quit 2>/dev/null || true)"
    if [ -n "$plugin" ]; then
        info "wtyczka NM Bluetooth: $plugin"
    else
        warn "brak wtyczki NM Bluetooth (libnm-device-plugin-bluetooth.so) — BT PAN nie zadziała; sprawdź pakiet network-manager"
    fi
    if command -v modinfo >/dev/null 2>&1 && modinfo bnep >/dev/null 2>&1; then
        info "moduł jądra bnep: jest"
    else
        warn "brak modułu jądra bnep — BT PAN nie zadziała"
    fi
    # Tylko pliki konfiguracji NM — nigdy system-connections (są tam hasła Wi-Fi).
    for f in /etc/NetworkManager/NetworkManager.conf /etc/NetworkManager/conf.d/*.conf; do
        [ -f "$f" ] || continue
        if grep -Eq '^[[:space:]]*unmanaged-devices[[:space:]]*=.*(bnep|type:bluetooth)' "$f"; then
            hits="$hits $f"
        fi
    done
    if [ -n "$hits" ]; then
        warn "reguła unmanaged-devices obejmuje bnep*/bluetooth w:$hits — NM nie podniesie PAN"
    else
        info "brak reguł unmanaged-devices dla bnep* — OK"
    fi
    ok
}

step_timesync() {
    step 9 "bcm-timesync.timer (zegar z nagłówka HTTPS Date)..."
    if ! unit_exists bcm-timesync.timer; then
        if [ "$DRY_RUN" = 0 ] || [ "$NO_UNITS" = 1 ]; then
            warn "brak bcm-timesync.timer — uruchom bez --no-units albo setup-x86.sh"
            return 0
        fi
    fi
    if [ "$(systemctl is-enabled bcm-timesync.timer 2>/dev/null || true)" = enabled ] \
        && systemctl is-active --quiet bcm-timesync.timer 2>/dev/null; then
        info "bcm-timesync.timer włączony i aktywny"
    else
        run systemctl enable --now bcm-timesync.timer || warn "nie udało się włączyć bcm-timesync.timer"
    fi
    ok
}

step_summary() {
    step 10 "Podsumowanie..."
    local b
    run systemctl daemon-reload || warn "systemctl daemon-reload nie powiódł się"
    run sync
    echo ""
    if [ "${#BACKUPS[@]}" -gt 0 ]; then
        if [ "$DRY_RUN" = 1 ]; then
            info "Kopie, które zostałyby utworzone:"
        else
            info "Kopie zapasowe (przywrócenie: sudo cp KOPIA ORYGINAŁ):"
        fi
        for b in "${BACKUPS[@]}"; do
            info "  $b"
        done
    else
        info "fstab i GRUB bez zmian — nowych kopii nie ma."
    fi
    if [ "$MIGRATION_PENDING" = 1 ]; then
        echo ""
        warn "config/local.yaml nie istnieje, a unit przechodzi na config/bcm_config_test.yaml —"
        warn "przed następnym startem BCM uruchom migrację ustawień z auta (polecenia w kroku 2)"
    fi
    echo ""
    printf '  %sPAMIĘTAJ — BIOS M910q (F1 przy starcie): Power -> After Power Loss -> Power On.%s\n' "$YELLOW" "$NC"
    printf '  %sBez tego po przekręceniu kluczyka (powrót zasilania) komputer nie włączy się sam.%s\n' "$YELLOW" "$NC"
    echo ""
    info "Czas startu (systemd-analyze):"
    systemd-analyze 2>/dev/null | sed 's/^/    /' \
        || info "  (start jeszcze trwa albo brak systemd-analyze)"
    info "Najwolniejsze jednostki (systemd-analyze blame | head -15):"
    systemd-analyze blame --no-pager 2>/dev/null | head -15 | sed 's/^/    /' || true
    info "/proc/cmdline:"
    info "  $(cat /proc/cmdline 2>/dev/null || echo '?')"
    echo ""
    if [ "$DRY_RUN" = 1 ]; then
        info "To był tryb próbny — nic nie zostało zmienione. Zastosowanie: sudo bash $0"
    else
        info "Gotowe. Pełny efekt (GRUB, fstab, journald) po ponownym uruchomieniu: sudo reboot"
    fi
}

main() {
    parse_args "$@"
    WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/bcm-harden.XXXXXX")"
    trap cleanup_work EXIT

    echo "========================================="
    echo " BCM — odporność na odcięcie prądu"
    echo "========================================="

    step_preconditions
    step_units_and_env
    step_journald
    step_sysctl
    step_fstab
    step_grub
    step_boot
    step_nm_bluetooth
    step_timesync
    step_summary
}

main "$@"
