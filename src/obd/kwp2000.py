"""KWP2000 protocol layer — ISO 14230 diagnostic services.

Implements the application-layer KWP2000 services used to communicate
with the Bosch EDC15C7 ECU: startDiagnosticSession, readDataByLocalIdentifier,
testerPresent (keepAlive), and stopDiagnosticSession.
"""

import time
from typing import Optional

from src.core.logger import get_logger
from src.obd.kline import KLine

log = get_logger("obd.kwp2000")

# KWP2000 Service IDs (SID)
SID_START_DIAG_SESSION = 0x10
SID_STOP_DIAG_SESSION = 0x20
SID_TESTER_PRESENT = 0x3E
SID_READ_DATA_BY_LOCAL_ID = 0x21
SID_READ_DATA_BY_COMMON_ID = 0x22

# Positive response = SID + 0x40
POSITIVE_RESPONSE_OFFSET = 0x40

# Diagnostic session types
DIAG_SESSION_DEFAULT = 0x81
DIAG_SESSION_EXTENDED = 0x89

# KWP2000 addressing (Bosch EDC15C7)
TESTER_ADDRESS = 0xF1  # Diagnostic tester
ECU_ADDRESS = 0x01      # Engine ECU


def _build_message(target: int, source: int, data: bytes) -> bytes:
    """Build a KWP2000 message with header and checksum.

    Format: [fmt] [target] [source] [data...] [checksum]
    fmt byte: 0x80 | length  (physical addressing, length in format byte)
    """
    length = len(data)
    if length > 63:
        # Use separate length byte (format 0xC0)
        header = bytes([0xC0, target, source, length])
    else:
        header = bytes([0x80 | length, target, source])

    msg = header + data
    checksum = sum(msg) & 0xFF
    return msg + bytes([checksum])


def _parse_response(raw: bytes) -> Optional[tuple[int, bytes]]:
    """Parse a KWP2000 response message.

    Returns:
        Tuple of (service_id, data_payload) or None if invalid.
    """
    if not raw or len(raw) < 4:
        return None

    fmt = raw[0]
    addr_mode = fmt & 0xC0

    if addr_mode == 0x80:
        data_len = fmt & 0x3F
        data_start = 3  # after fmt, target, source
    elif addr_mode == 0xC0:
        data_len = raw[3]
        data_start = 4  # after fmt, target, source, length
    else:
        return None

    data_end = data_start + data_len
    if data_end + 1 > len(raw):  # +1 for checksum
        return None

    data = raw[data_start:data_end]
    if not data:
        return None

    return (data[0], data[1:])


class KWP2000:
    """KWP2000 diagnostic protocol over K-Line.

    Usage:
        kline = KLine("/dev/ttyS3")
        kline.open()
        kwp = KWP2000(kline)
        if kwp.start_session():
            data = kwp.read_local_id(0x01)  # read RPM
            kwp.stop_session()
    """

    def __init__(self, kline: KLine, ecu_address: int = ECU_ADDRESS) -> None:
        self.kline = kline
        self.ecu_address = ecu_address
        self._session_active = False
        self._last_request_time = 0.0

    @property
    def session_active(self) -> bool:
        return self._session_active

    def _send_request(self, service_id: int, data: bytes = b"") -> Optional[tuple[int, bytes]]:
        """Send a KWP2000 request and wait for response.

        Returns:
            Tuple of (response_sid, payload) or None on failure.
        """
        # Respect P3 timing (min time between requests)
        elapsed = time.time() - self._last_request_time
        if elapsed < 0.055:
            time.sleep(0.055 - elapsed)

        msg = _build_message(self.ecu_address, TESTER_ADDRESS, bytes([service_id]) + data)
        self.kline.send(msg)
        self._last_request_time = time.time()

        # Wait for response
        raw = self.kline.receive(timeout=0.5)
        if raw is None:
            log.debug("No response for SID 0x%02X", service_id)
            return None

        result = _parse_response(raw)
        if result is None:
            log.debug("Invalid response for SID 0x%02X", service_id)
            return None

        resp_sid, payload = result

        # Check for negative response (0x7F)
        if resp_sid == 0x7F:
            if len(payload) >= 2:
                log.warning("Negative response: SID=0x%02X, NRC=0x%02X",
                            payload[0], payload[1])
            return None

        # Verify positive response
        expected = service_id + POSITIVE_RESPONSE_OFFSET
        if resp_sid != expected:
            log.warning("Unexpected response SID: 0x%02X (expected 0x%02X)",
                        resp_sid, expected)
            return None

        return (resp_sid, payload)

    def init_fast(self) -> bool:
        """Fast initialization (address-based, no 5-baud).

        Sends a startCommunication request directly at 10400 baud.
        Some ECUs support this instead of slow 5-baud init.
        """
        log.info("Attempting fast init...")
        msg = _build_message(self.ecu_address, TESTER_ADDRESS,
                             bytes([0x81]))  # startCommunication
        self.kline.send(msg)
        self._last_request_time = time.time()

        raw = self.kline.receive(timeout=0.5)
        if raw:
            result = _parse_response(raw)
            if result and result[0] == 0xC1:  # positive response
                log.info("Fast init successful")
                self._session_active = True
                return True

        log.info("Fast init failed, will need 5-baud init")
        return False

    def start_session(self, session_type: int = DIAG_SESSION_DEFAULT) -> bool:
        """Start a diagnostic session with the ECU.

        Args:
            session_type: Session type (0x81=default, 0x89=extended).

        Returns:
            True if session started successfully.
        """
        result = self._send_request(SID_START_DIAG_SESSION, bytes([session_type]))
        if result:
            log.info("Diagnostic session started (type=0x%02X)", session_type)
            self._session_active = True
            return True

        log.warning("Failed to start diagnostic session")
        return False

    def stop_session(self) -> bool:
        """Stop the current diagnostic session."""
        result = self._send_request(SID_STOP_DIAG_SESSION)
        self._session_active = False
        if result:
            log.info("Diagnostic session stopped")
            return True
        return False

    def tester_present(self) -> bool:
        """Send testerPresent keepalive to prevent session timeout.

        Should be called at least every 2 seconds during active session.
        """
        result = self._send_request(SID_TESTER_PRESENT)
        return result is not None

    def read_local_id(self, local_id: int) -> Optional[bytes]:
        """Read data by local identifier (readDataByLocalIdentifier).

        Args:
            local_id: Local identifier for the data to read.

        Returns:
            Raw data bytes (without SID and ID echo), or None on failure.
        """
        result = self._send_request(SID_READ_DATA_BY_LOCAL_ID, bytes([local_id]))
        if result:
            _, payload = result
            # Payload starts with the echoed local ID, then data
            if len(payload) > 1 and payload[0] == local_id:
                return payload[1:]
            return payload
        return None

    def read_common_id(self, common_id: int) -> Optional[bytes]:
        """Read data by common identifier (readDataByCommonIdentifier).

        Args:
            common_id: Two-byte common identifier (e.g., 0xF190 for VIN).

        Returns:
            Raw data bytes, or None on failure.
        """
        id_bytes = common_id.to_bytes(2, "big")
        result = self._send_request(SID_READ_DATA_BY_COMMON_ID, id_bytes)
        if result:
            _, payload = result
            if len(payload) > 2:
                return payload[2:]  # skip echoed ID
            return payload
        return None
