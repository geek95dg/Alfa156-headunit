"""x86 Mock ECU simulator — responds to KWP2000 requests with realistic data.

Creates a virtual serial pair (PTY) so the OBD reader can communicate
with this simulated ECU as if it were a real Bosch EDC15C7 over K-Line.
"""

import math
import os
import select
import time
import threading
from typing import Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("obd.simulator")

# KWP2000 SIDs
SID_START_DIAG = 0x10
SID_STOP_DIAG = 0x20
SID_TESTER_PRESENT = 0x3E
SID_READ_LOCAL_ID = 0x21
SID_START_COMM = 0x81
POSITIVE_OFFSET = 0x40


def _checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def _build_response(target: int, source: int, data: bytes) -> bytes:
    """Build a KWP2000 response message."""
    length = len(data)
    if length > 63:
        header = bytes([0xC0, target, source, length])
    else:
        header = bytes([0x80 | length, target, source])
    msg = header + data
    return msg + bytes([_checksum(msg)])


class ECUSimulator:
    """Simulated Bosch EDC15C7 ECU that responds to KWP2000 requests.

    Creates a PTY pair for serial communication. The reader connects
    to `self.reader_port`, while the simulator listens on the internal end.
    """

    TESTER_ADDR = 0xF1
    ECU_ADDR = 0x01

    def __init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._session_active = False
        self._t = 0.0

        # PTY pair
        self._master_fd: Optional[int] = None
        self._slave_fd: Optional[int] = None
        self.reader_port: str = ""

    def start(self) -> str:
        """Create PTY pair and start simulator thread.

        Returns:
            Path to the reader-side serial port (e.g., /dev/pts/3).
        """
        self._master_fd, self._slave_fd = os.openpty()
        self.reader_port = os.ttyname(self._slave_fd)

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        log.info("ECU simulator started on PTY: %s", self.reader_port)
        return self.reader_port

    def stop(self) -> None:
        """Stop the simulator and close PTY."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
        if self._slave_fd is not None:
            try:
                os.close(self._slave_fd)
            except OSError:
                pass
        self._master_fd = None
        self._slave_fd = None
        log.info("ECU simulator stopped")

    def _generate_value(self, local_id: int) -> bytes:
        """Generate realistic simulated data for a given PID."""
        self._t += 0.05

        if local_id == 0x01:  # RPM (2 bytes, ÷ 0.25)
            rpm = 2200 + 1200 * math.sin(self._t * 0.4) + 80 * math.sin(self._t * 2.3)
            rpm = max(750, min(5000, rpm))
            raw = int(rpm / 0.25)
            return raw.to_bytes(2, "big")

        elif local_id == 0x02:  # Speed (1 byte)
            rpm_approx = 2200 + 1200 * math.sin(self._t * 0.4)
            speed = max(0, min(220, (rpm_approx - 800) * 0.04))
            return bytes([int(speed)])

        elif local_id == 0x03:  # Coolant temp (1 byte, +40 offset)
            temp = 60 + 30 * (1 - math.exp(-self._t * 0.01)) + 2 * math.sin(self._t * 0.05)
            return bytes([int(temp + 40)])

        elif local_id == 0x04:  # Fuel rate (2 bytes, ÷ 0.01)
            rpm_approx = 2200 + 1200 * math.sin(self._t * 0.4)
            fuel = max(0.5, 1.0 + (rpm_approx / 1000) * 2.5 + 0.3 * math.sin(self._t * 0.7))
            raw = int(fuel / 0.01)
            return raw.to_bytes(2, "big")

        elif local_id == 0x05:  # Injector qty (2 bytes, ÷ 0.01)
            qty = 15 + 10 * math.sin(self._t * 0.5)
            raw = int(max(0, qty) / 0.01)
            return raw.to_bytes(2, "big")

        elif local_id == 0x06:  # Battery voltage (1 byte, ÷ 0.1)
            voltage = 13.8 + 0.4 * math.sin(self._t * 0.1)
            return bytes([int(voltage / 0.1)])

        elif local_id == 0x07:  # Turbo pressure (2 bytes, mbar)
            pressure = 1200 + 400 * math.sin(self._t * 0.3)
            return int(max(0, pressure)).to_bytes(2, "big")

        elif local_id == 0x08:  # Intake air temp (1 byte, +40 offset)
            temp = 30 + 10 * math.sin(self._t * 0.02)
            return bytes([int(temp + 40)])

        elif local_id == 0x09:  # Throttle position (1 byte, ÷ 0.4)
            pos = 30 + 25 * math.sin(self._t * 0.6)
            return bytes([int(max(0, min(100, pos)) / 0.4)])

        # Unknown PID — return empty
        return b"\x00"

    def _handle_message(self, data: bytes) -> Optional[bytes]:
        """Process an incoming KWP2000 request and return response bytes."""
        if not data:
            return None

        sid = data[0]

        if sid == SID_START_COMM:
            # startCommunication — positive response 0xC1
            self._session_active = True
            return bytes([SID_START_COMM + POSITIVE_OFFSET, 0x01, 0x8A])  # KB1, KB2

        elif sid == SID_START_DIAG:
            if len(data) > 1:
                session_type = data[1]
                self._session_active = True
                return bytes([sid + POSITIVE_OFFSET, session_type])
            return None

        elif sid == SID_STOP_DIAG:
            self._session_active = False
            return bytes([sid + POSITIVE_OFFSET])

        elif sid == SID_TESTER_PRESENT:
            return bytes([sid + POSITIVE_OFFSET])

        elif sid == SID_READ_LOCAL_ID:
            if len(data) > 1:
                local_id = data[1]
                value = self._generate_value(local_id)
                return bytes([sid + POSITIVE_OFFSET, local_id]) + value
            return None

        else:
            # Unknown service — negative response
            return bytes([0x7F, sid, 0x11])  # serviceNotSupported

    def _run(self) -> None:
        """Main simulator loop — read requests, send responses."""
        buf = bytearray()

        while self._running:
            try:
                # Wait for data on master fd (with timeout so we can check _running)
                if self._master_fd is None:
                    break
                ready, _, _ = select.select([self._master_fd], [], [], 0.05)
                if ready:
                    try:
                        incoming = os.read(self._master_fd, 256)
                        if incoming:
                            buf.extend(incoming)
                    except OSError:
                        time.sleep(0.01)
                        continue

                # Try to parse a complete message from buffer
                if len(buf) >= 4:
                    msg, consumed = self._try_parse(buf)
                    if msg is not None and consumed > 0:
                        buf = buf[consumed:]
                        response_data = self._handle_message(msg)
                        if response_data:
                            resp = _build_response(
                                self.TESTER_ADDR, self.ECU_ADDR, response_data
                            )
                            time.sleep(0.01)  # P2 timing
                            os.write(self._master_fd, resp)
                    elif consumed == 0 and len(buf) > 64:
                        # Buffer growing without valid messages — flush
                        buf.clear()
                else:
                    time.sleep(0.005)

            except Exception:
                if self._running:
                    log.exception("Simulator error")
                    time.sleep(0.1)

    def _try_parse(self, buf: bytearray) -> tuple[Optional[bytes], int]:
        """Try to parse a complete KWP2000 message from buffer.

        Returns:
            (data_payload, bytes_consumed) or (None, 0) if incomplete.
        """
        if len(buf) < 4:
            return None, 0

        fmt = buf[0]
        addr_mode = fmt & 0xC0

        if addr_mode == 0x80:
            data_len = fmt & 0x3F
            header_len = 3  # fmt + target + source
        elif addr_mode == 0xC0:
            if len(buf) < 4:
                return None, 0
            data_len = buf[3]
            header_len = 4  # fmt + target + source + length
        else:
            # Skip unknown byte
            return None, 1

        total_len = header_len + data_len + 1  # +1 checksum
        if len(buf) < total_len:
            return None, 0

        msg = bytes(buf[:total_len])

        # Verify checksum
        expected_cs = sum(msg[:-1]) & 0xFF
        if expected_cs != msg[-1]:
            # Bad checksum — skip first byte
            return None, 1

        # Extract data payload
        data = msg[header_len:header_len + data_len]
        return data, total_len


def start_obd(config, event_bus: EventBus, **kwargs) -> None:
    """Entry point called from main.py to start the OBD module.

    On x86: starts the ECU simulator + KWP2000 reader.
    On OPi: connects to real UART via L9637D.
    """
    from src.obd.kline import KLine
    from src.obd.kwp2000 import KWP2000
    from src.obd.edc15c7 import EDC15C7Reader

    platform = config.platform

    if platform == "x86":
        # Start mock ECU simulator
        simulator = ECUSimulator()
        port = simulator.start()
        time.sleep(0.3)  # let PTY settle
    else:
        port = config.get("serial.kline.port_opi", "/dev/ttyS3")
        simulator = None

    # Open K-Line (echo=True on real K-Line, False on PTY simulator)
    kline = KLine(port, echo=(platform == "opi"))
    kline.open()

    # Initialize connection
    kwp = KWP2000(kline, ecu_address=config.get("serial.kline.ecu_address", 0x01))

    if platform == "x86":
        # On x86, use fast init (simulator supports it)
        if not kwp.init_fast():
            log.warning("Fast init failed on simulator")
    else:
        # On OPi, perform 5-baud init
        ecu_addr = config.get("serial.kline.ecu_address", 0x01)
        if not kline.five_baud_init(ecu_addr):
            log.error("5-baud init failed — cannot communicate with ECU")
            if simulator:
                simulator.stop()
            kline.close()
            return

    # Start diagnostic session
    if not kwp.start_session():
        log.error("Failed to start diagnostic session")
        if simulator:
            simulator.stop()
        kline.close()
        return

    # Start polling
    reader = EDC15C7Reader(kwp, event_bus)
    reader.start()

    log.info("OBD module running — polling ECU data")

    # Store references for cleanup (attached to event_bus for access)
    event_bus.publish("obd._internals", {
        "simulator": simulator,
        "kline": kline,
        "kwp": kwp,
        "reader": reader,
    })
