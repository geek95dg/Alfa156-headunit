#!/usr/bin/env python3
"""K-Line / KWP2000 sniffer + skaner PID — narzędzie do inżynierii wstecznej.

Trzy tryby:

  --passive   PODSŁUCH: tylko czyta magistralę i dekoduje ramki KWP2000.
              Podłącz drugi adapter (CP2102/VIAKEN) RÓWNOLEGLE do K-Line
              i uruchom MES/Multiecuscan — zobaczysz komplet par
              request/response, których MES używa do odczytu funkcji.
              To najpewniejsza metoda poznania kodów PID.

  --scan      SKANER: aktywnie odpytuje ECU readDataByLocalIdentifier
              (0x21) dla zakresu ID i pokazuje, które zwracają dane.
              Używa tego samego kodu co BCM (src.obd). NIE uruchamiaj
              równocześnie z MES — dwóch masterów na magistrali = kolizje.

  --replay    Wysyła jedną, podaną ręcznie ramkę (hex) i pokazuje
              odpowiedź. Do weryfikacji pojedynczego kodu znalezionego
              podsłuchem.

Przykłady:
    python tools/kline_sniffer.py --passive --port /dev/ttyUSB0
    python tools/kline_sniffer.py --scan --port /dev/ttyUSB0 --from 0x01 --to 0x40
    python tools/kline_sniffer.py --replay 68 6A F1 21 0B --port /dev/ttyUSB0

Zależności: tylko pyserial (pip install pyserial). Tryb --scan importuje
src.obd.* — uruchamiaj z katalogu głównego repo.
"""

import argparse
import sys
import time


# --- Dekoder ramek KWP2000 (współdzielony przez tryby) ----------------------

# Znane nazwy usług (SID) — żeby log był czytelny
SID_NAMES = {
    0x10: "startDiagnosticSession",
    0x11: "ecuReset",
    0x14: "clearDiagnosticInformation",
    0x18: "readDTCByStatus",
    0x1A: "readEcuIdentification",
    0x20: "stopDiagnosticSession",
    0x21: "readDataByLocalIdentifier",
    0x22: "readDataByCommonIdentifier",
    0x23: "readMemoryByAddress",
    0x27: "securityAccess",
    0x2E: "writeDataByCommonId",
    0x30: "inputOutputControl",
    0x31: "startRoutineByLocalId",
    0x3E: "testerPresent",
    0x81: "startCommunication",
    0x82: "stopCommunication",
}
# Kody błędu (NRC) w odpowiedzi negatywnej 0x7F
NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x78: "responsePending",
}


def parse_frame(buf: bytes):
    """Rozłóż jedną ramkę KWP2000 na (długość_całkowita, opis) albo (0, None).

    Format ISO 14230:
      [fmt] [target] [source] [dane...] [checksum]
      fmt: bity 7-6 = tryb adresowania, bity 5-0 = długość (jeśli != 0)
      gdy długość w fmt == 0 → osobny bajt długości po adresach.
    """
    if len(buf) < 4:
        return 0, None
    fmt = buf[0]
    addr_mode = fmt & 0xC0
    length_in_fmt = fmt & 0x3F

    if addr_mode in (0x80, 0xC0, 0x00):
        if length_in_fmt:
            data_len = length_in_fmt
            hdr = 3  # fmt + target + source
        else:
            if len(buf) < 4:
                return 0, None
            data_len = buf[3]
            hdr = 4  # fmt + target + source + len
    else:
        return 1, None  # nieznany bajt — przesuń o 1

    total = hdr + data_len + 1  # +1 checksum
    if len(buf) < total:
        return 0, None  # niekompletna — czekaj na resztę

    frame = buf[:total]
    if (sum(frame[:-1]) & 0xFF) != frame[-1]:
        return 1, None  # zła suma — przesuń o 1 i spróbuj resync

    target = frame[1]
    source = frame[2]
    data = frame[hdr:hdr + data_len]
    sid = data[0] if data else None

    if sid == 0x7F and len(data) >= 3:
        svc = SID_NAMES.get(data[1], f"0x{data[1]:02X}")
        nrc = NRC_NAMES.get(data[2], f"0x{data[2]:02X}")
        desc = f"NEG  {svc} -> {nrc}"
    elif sid is not None and sid >= 0x40 and (sid - 0x40) in SID_NAMES:
        svc = SID_NAMES[sid - 0x40]
        desc = f"RESP {svc}  data={data[1:].hex(' ')}"
    else:
        svc = SID_NAMES.get(sid, f"0x{sid:02X}" if sid is not None else "?")
        desc = f"REQ  {svc}  args={data[1:].hex(' ')}"

    line = (f"[{source:02X}->{target:02X}] {frame.hex(' ')}  |  {desc}")
    return total, line


# --- Tryb PASYWNY -----------------------------------------------------------

def run_passive(args):
    import serial
    print(f"# PODSŁUCH na {args.port} @ {args.baud} baud — Ctrl+C aby zakończyć")
    print("# Uruchom teraz MES/Multiecuscan i wejdź w podgląd parametrów.\n")
    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    buf = bytearray()
    logf = open(args.log, "w") if args.log else None
    try:
        while True:
            chunk = ser.read(256)
            if chunk:
                buf.extend(chunk)
            # Spróbuj wyciąć jak najwięcej kompletnych ramek
            while len(buf) >= 4:
                consumed, line = parse_frame(bytes(buf))
                if consumed == 0:
                    break  # niekompletna ramka — dobierz więcej bajtów
                if line:
                    stamp = time.strftime("%H:%M:%S")
                    out = f"{stamp}  {line}"
                    print(out)
                    if logf:
                        logf.write(out + "\n")
                        logf.flush()
                del buf[:consumed]
            if len(buf) > 4096:
                del buf[:2048]  # awaryjny bezpiecznik
    except KeyboardInterrupt:
        print("\n# Zakończono.")
    finally:
        ser.close()
        if logf:
            logf.close()


# --- Tryb SKANERA (aktywny, używa kodu BCM) ---------------------------------

def run_scan(args):
    from src.obd.kline import KLine
    from src.obd.kwp2000 import KWP2000

    print(f"# SKANER readDataByLocalIdentifier na {args.port}")
    print(f"# Zakres ID: 0x{args.range_from:02X}..0x{args.range_to:02X}")
    print("# UWAGA: odłącz MES — tylko jeden master na magistrali.\n")

    kl = KLine(args.port, echo=True)
    kl.open()
    if not kl.five_baud_init(args.ecu):
        print("! 5-baud init nieudany — sprawdź okablowanie/zapłon (ON).")
        kl.close()
        return
    kwp = KWP2000(kl, ecu_address=args.ecu)
    if not kwp.start_session():
        print("! Nie udało się otworzyć sesji diagnostycznej.")
        kl.close()
        return

    found = []
    last_keepalive = time.time()
    for lid in range(args.range_from, args.range_to + 1):
        if time.time() - last_keepalive > 2.0:
            kwp.tester_present()
            last_keepalive = time.time()
        raw = kwp.read_local_id(lid)
        if raw:
            print(f"  ID 0x{lid:02X}  ->  {raw.hex(' ')}  ({len(raw)} B)")
            found.append((lid, raw))
        time.sleep(0.06)  # respektuj P3

    kwp.stop_session()
    kl.close()
    print(f"\n# Znaleziono {len(found)} aktywnych ID. Skopiuj je do "
          "src/obd/edc15c7.py (tabela PIDS) po ustaleniu skali/offsetu.")


# --- Tryb REPLAY (jedna ramka) ----------------------------------------------

def run_replay(args):
    import serial
    payload = bytes(int(b, 16) for b in args.replay)
    print(f"# Wysyłam: {payload.hex(' ')}")
    ser = serial.Serial(args.port, args.baud, timeout=0.5)
    ser.reset_input_buffer()
    for byte in payload:
        ser.write(bytes([byte]))
        time.sleep(0.005)  # P4
    time.sleep(0.06)
    resp = ser.read(64)
    ser.close()
    if resp:
        _, line = parse_frame(resp)
        print(f"# Odpowiedź surowa: {resp.hex(' ')}")
        if line:
            print(f"# Dekod: {line}")
    else:
        print("# Brak odpowiedzi (timeout).")


def main():
    ap = argparse.ArgumentParser(description="K-Line / KWP2000 sniffer + skaner PID")
    ap.add_argument("--port", default="/dev/ttyUSB0", help="Port szeregowy adaptera")
    ap.add_argument("--baud", type=int, default=10400, help="Baud (domyślnie 10400)")
    ap.add_argument("--ecu", type=lambda x: int(x, 0), default=0x01,
                    help="Adres ECU dla --scan (domyślnie 0x01 = silnik EDC15)")
    ap.add_argument("--log", default=None, help="Zapisuj podsłuch do pliku")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--passive", action="store_true", help="Tryb podsłuchu")
    mode.add_argument("--scan", action="store_true", help="Aktywny skan PID")
    mode.add_argument("--replay", nargs="+", metavar="HEX",
                      help="Wyślij jedną ramkę (bajty hex, np. 68 6A F1 21 0B)")
    ap.add_argument("--from", dest="range_from", type=lambda x: int(x, 0),
                    default=0x01, help="--scan: pierwsze ID")
    ap.add_argument("--to", dest="range_to", type=lambda x: int(x, 0),
                    default=0x40, help="--scan: ostatnie ID")
    args = ap.parse_args()

    if args.passive:
        run_passive(args)
    elif args.scan:
        run_scan(args)
    elif args.replay:
        run_replay(args)


if __name__ == "__main__":
    sys.exit(main())
