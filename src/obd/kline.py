"""K-Line physical layer — 5-baud initialization, 10400 baud serial, timing.

Implements the ISO 14230 (KWP2000) physical layer over a K-Line bus
using an L9637D transceiver on OPi or a PTY pair on x86.
"""

import time
from typing import Optional

from src.core.logger import get_logger

log = get_logger("obd.kline")

# K-Line timing constants (ISO 14230)
BAUD_RATE = 10400
FIVE_BAUD_BIT_TIME = 0.2  # 200ms per bit at 5 baud
P1_MAX = 0.02   # 20ms max inter-byte time (ECU response)
P2_MIN = 0.025  # 25ms min time between tester request and ECU response
P2_MAX = 0.050  # 50ms max
P3_MIN = 0.055  # 55ms min time between ECU response and next tester request
P4_MIN = 0.005  # 5ms min inter-byte time (tester request)


class KLine:
    """K-Line physical layer for ISO 14230 / KWP2000 communication.

    On OPi: uses pyserial with real UART (/dev/ttyS3) via L9637D transceiver.
    On x86: uses pyserial with a PTY pair created by the simulator.
    """

    def __init__(self, port: str, baudrate: int = BAUD_RATE, echo: bool = False) -> None:
        self.port = port
        self.baudrate = baudrate
        self._serial = None
        self._connected = False
        self._echo = echo  # True on real K-Line (half-duplex), False on PTY

    def open(self) -> None:
        """Open the serial port."""
        import serial
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5,
        )
        self._serial.reset_input_buffer()
        log.info("K-Line opened: %s @ %d baud", self.port, self.baudrate)

    def close(self) -> None:
        """Close the serial port."""
        if self._serial and self._serial.is_open:
            self._serial.close()
            log.info("K-Line closed: %s", self.port)
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def five_baud_init(self, ecu_address: int = 0x01) -> bool:
        """Perform 5-baud initialization sequence (ISO 14230).

        Sends the ECU address byte at 5 baud by bit-banging the TX line
        using serial break signals, then switches to 10400 baud for the
        handshake.

        Args:
            ecu_address: Target ECU address (0x01 for EDC15C7).

        Returns:
            True if initialization succeeded (key bytes received).
        """
        if not self._serial:
            log.error("Serial port not open")
            return False

        log.info("Starting 5-baud init for ECU address 0x%02X...", ecu_address)

        # Build the 10-bit frame: start(0) + 8 data bits (LSB first) + stop(1)
        bits = [0]  # start bit
        for i in range(8):
            bits.append((ecu_address >> i) & 1)
        bits.append(1)  # stop bit

        # Send each bit by toggling break state
        # Break = logic 0 (dominant), No break = logic 1 (recessive)
        try:
            for bit in bits:
                if bit == 0:
                    self._serial.break_condition = True
                else:
                    self._serial.break_condition = False
                time.sleep(FIVE_BAUD_BIT_TIME)

            # Ensure line returns to idle (recessive/high)
            self._serial.break_condition = False
            time.sleep(FIVE_BAUD_BIT_TIME)

            # Now read the sync byte and key bytes from ECU
            self._serial.reset_input_buffer()
            time.sleep(0.3)  # W1 wait time (up to 300ms for ECU response)

            response = self._serial.read(3)  # sync + KB1 + KB2
            if len(response) < 3:
                log.warning("5-baud init: incomplete response (%d bytes)", len(response))
                return False

            sync_byte = response[0]
            key_byte1 = response[1]
            key_byte2 = response[2]

            log.info("5-baud init response: sync=0x%02X KB1=0x%02X KB2=0x%02X",
                     sync_byte, key_byte1, key_byte2)

            # Validate sync byte (should be 0x55)
            if sync_byte != 0x55:
                log.warning("Invalid sync byte: 0x%02X (expected 0x55)", sync_byte)
                return False

            # Send inverted key byte 2 as acknowledgement
            ack = (~key_byte2) & 0xFF
            time.sleep(P4_MIN)
            self._serial.write(bytes([ack]))

            # Read ECU's inverted address acknowledgement
            time.sleep(0.05)
            ecu_ack = self._serial.read(1)
            if len(ecu_ack) == 1:
                expected_ack = (~ecu_address) & 0xFF
                if ecu_ack[0] == expected_ack:
                    log.info("5-baud init successful! ECU acknowledged.")
                    self._connected = True
                    return True
                else:
                    log.warning("ECU ack mismatch: 0x%02X (expected 0x%02X)",
                                ecu_ack[0], expected_ack)
            else:
                log.warning("No ECU acknowledgement received")

        except Exception:
            log.exception("5-baud init failed")

        return False

    def send(self, data: bytes) -> int:
        """Send data on K-Line with inter-byte timing.

        Returns number of bytes sent.
        """
        if not self._serial:
            return 0

        sent = 0
        for byte in data:
            self._serial.write(bytes([byte]))
            sent += 1
            if sent < len(data):
                time.sleep(P4_MIN)  # inter-byte delay

        # Read back echo (K-Line is half-duplex, we see our own TX)
        # On PTY/simulator, there's no echo, so skip
        if self._echo:
            time.sleep(0.005)
            echo = self._serial.read(len(data))
            if echo != data:
                log.debug("Echo mismatch: sent %s, got %s", data.hex(), echo.hex())

        return sent

    def receive(self, timeout: float = 0.5) -> Optional[bytes]:
        """Receive a complete KWP2000 message from K-Line.

        Reads the header to determine message length, then reads
        the full payload + checksum.

        Returns:
            Complete message bytes (header + data + checksum), or None on timeout.
        """
        if not self._serial:
            return None

        self._serial.timeout = timeout

        # Read format byte (first byte of header)
        fmt_byte = self._serial.read(1)
        if not fmt_byte:
            return None

        fmt = fmt_byte[0]
        buf = bytearray(fmt_byte)

        # Determine header length and data length from format byte
        addr_mode = fmt & 0xC0  # top 2 bits: addressing mode
        length_in_fmt = fmt & 0x3F  # bottom 6 bits: length (if present)

        # Read target and source address bytes (if physical addressing)
        if addr_mode == 0x80:  # physical addressing with length in format
            # Read target + source (2 bytes)
            addr_bytes = self._serial.read(2)
            if len(addr_bytes) < 2:
                return None
            buf.extend(addr_bytes)
            data_len = length_in_fmt

        elif addr_mode == 0xC0:  # physical addressing, separate length byte
            addr_bytes = self._serial.read(2)
            if len(addr_bytes) < 2:
                return None
            buf.extend(addr_bytes)
            len_byte = self._serial.read(1)
            if not len_byte:
                return None
            buf.extend(len_byte)
            data_len = len_byte[0]

        elif addr_mode == 0x00:  # functional addressing with length in format
            data_len = length_in_fmt
            # No address bytes in some modes; read remaining based on context
            # For our ECU, we typically use 0x80 mode
            pass

        else:
            # Unknown format — try to read remaining bytes
            data_len = length_in_fmt

        # Read data + checksum
        remaining = data_len + 1  # +1 for checksum
        payload = self._serial.read(remaining)
        if len(payload) < remaining:
            log.debug("Incomplete message: expected %d more bytes, got %d",
                      remaining, len(payload))
            return None
        buf.extend(payload)

        # Verify checksum
        checksum = sum(buf[:-1]) & 0xFF
        if checksum != buf[-1]:
            log.debug("Checksum error: calc=0x%02X, recv=0x%02X", checksum, buf[-1])
            return None

        return bytes(buf)

    def flush(self) -> None:
        """Flush input/output buffers."""
        if self._serial:
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
