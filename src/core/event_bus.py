"""Publish/subscribe message bus for inter-module communication.

Modules publish events (e.g. "obd.rpm", "env.temperature") and other
modules subscribe to them with callback functions.

Modes:
  - In-process (default): synchronous dispatch, single-process.
  - IPC server: listens on a Unix domain socket, relays events to
    connected client processes. Used when running modules as separate
    systemd services on the OPi.
  - IPC client: connects to the IPC server socket, forwards local
    publishes to the server, receives remote events and dispatches
    them to local subscribers.

The wire protocol is newline-delimited JSON:
    {"topic": "obd.rpm", "value": 3200, "ts": 1700000000.0}
"""

import json
import os
import select
import socket
import threading
import time
from collections import defaultdict
from typing import Any, Callable, Optional

from .logger import get_logger

log = get_logger("event_bus")

# Type alias for event callbacks
EventCallback = Callable[[str, Any, float], None]

# Default socket path for IPC
DEFAULT_SOCKET_PATH = "/run/bcm/event_bus.sock"


class EventBus:
    """Thread-safe publish/subscribe event bus.

    Usage (in-process):
        bus = EventBus()
        bus.subscribe("obd.rpm", on_rpm)
        bus.publish("obd.rpm", 3200)

    Usage (IPC server — runs in bcm-power service):
        bus = EventBus()
        bus.start_ipc_server()

    Usage (IPC client — runs in other services):
        bus = EventBus()
        bus.connect_ipc()
        bus.subscribe("obd.rpm", on_rpm)
        bus.publish("obd.rpm", 3200)  # relayed via server
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventCallback]] = defaultdict(list)
        self._wildcard_subscribers: list[EventCallback] = []
        self._lock = threading.Lock()
        self._last_values: dict[str, tuple[Any, float]] = {}

        # IPC state
        self._ipc_server_sock: Optional[socket.socket] = None
        self._ipc_client_sock: Optional[socket.socket] = None
        self._ipc_clients: list[socket.socket] = []
        self._ipc_clients_lock = threading.Lock()
        self._ipc_running = False

    def subscribe(self, topic: str, callback: EventCallback) -> None:
        """Subscribe to a specific topic.

        Args:
            topic: Event topic string (e.g. "obd.rpm", "env.temperature").
                   Use "*" to subscribe to all events.
            callback: Function called with (topic, value, timestamp).
        """
        with self._lock:
            if topic == "*":
                self._wildcard_subscribers.append(callback)
                log.debug("Wildcard subscriber added: %s", callback.__name__)
            else:
                self._subscribers[topic].append(callback)
                log.debug("Subscriber added for '%s': %s", topic, callback.__name__)

    def unsubscribe(self, topic: str, callback: EventCallback) -> None:
        """Remove a callback from a topic."""
        with self._lock:
            if topic == "*":
                try:
                    self._wildcard_subscribers.remove(callback)
                except ValueError:
                    pass
            else:
                try:
                    self._subscribers[topic].remove(callback)
                except ValueError:
                    pass

    def publish(self, topic: str, value: Any = None) -> None:
        """Publish an event to all local subscribers and relay via IPC.

        Args:
            topic: Event topic string.
            value: Payload data (any JSON-serializable type).
        """
        timestamp = time.time()

        with self._lock:
            self._last_values[topic] = (value, timestamp)
            callbacks = list(self._subscribers.get(topic, []))
            wildcards = list(self._wildcard_subscribers)

        for cb in callbacks + wildcards:
            try:
                cb(topic, value, timestamp)
            except Exception:
                log.exception("Error in subscriber %s for topic '%s'", cb.__name__, topic)

        # Relay to IPC if active
        if self._ipc_server_sock is not None:
            self._ipc_broadcast(topic, value, timestamp)
        elif self._ipc_client_sock is not None:
            self._ipc_send(topic, value, timestamp)

    def get_last(self, topic: str) -> Optional[tuple[Any, float]]:
        """Get the last published value for a topic.

        Returns:
            Tuple of (value, timestamp) or None if never published.
        """
        with self._lock:
            return self._last_values.get(topic)

    def topics(self) -> list[str]:
        """Return a list of all topics that have been published at least once."""
        with self._lock:
            return list(self._last_values.keys())

    def clear(self) -> None:
        """Remove all subscribers and cached values."""
        with self._lock:
            self._subscribers.clear()
            self._wildcard_subscribers.clear()
            self._last_values.clear()

    # ------------------------------------------------------------------
    # IPC Server (run by the primary service, e.g. bcm-power)
    # ------------------------------------------------------------------

    def start_ipc_server(self, socket_path: str = DEFAULT_SOCKET_PATH) -> None:
        """Start the Unix domain socket server for cross-process events.

        Args:
            socket_path: Path for the Unix socket file.
        """
        if self._ipc_running:
            return

        # Ensure directory exists
        sock_dir = os.path.dirname(socket_path)
        if sock_dir:
            os.makedirs(sock_dir, exist_ok=True)

        # Remove stale socket
        if os.path.exists(socket_path):
            os.unlink(socket_path)

        self._ipc_server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._ipc_server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._ipc_server_sock.bind(socket_path)
        self._ipc_server_sock.listen(16)
        self._ipc_server_sock.setblocking(False)
        self._ipc_running = True

        thread = threading.Thread(target=self._ipc_server_loop, daemon=True)
        thread.start()
        log.info("IPC server started on %s", socket_path)

    def stop_ipc_server(self) -> None:
        """Stop the IPC server and disconnect all clients."""
        self._ipc_running = False

        with self._ipc_clients_lock:
            for client in self._ipc_clients:
                try:
                    client.close()
                except OSError:
                    pass
            self._ipc_clients.clear()

        if self._ipc_server_sock:
            try:
                self._ipc_server_sock.close()
            except OSError:
                pass
            self._ipc_server_sock = None
            log.info("IPC server stopped")

    def _ipc_server_loop(self) -> None:
        """Accept connections and receive events from clients."""
        while self._ipc_running:
            readable = [self._ipc_server_sock]
            with self._ipc_clients_lock:
                readable.extend(self._ipc_clients)

            try:
                ready, _, _ = select.select(readable, [], [], 0.5)
            except (ValueError, OSError):
                break

            for sock in ready:
                if sock is self._ipc_server_sock:
                    try:
                        client, _ = self._ipc_server_sock.accept()
                        client.setblocking(False)
                        with self._ipc_clients_lock:
                            self._ipc_clients.append(client)
                        log.info("IPC client connected (fd=%d)", client.fileno())
                    except OSError:
                        pass
                else:
                    self._ipc_handle_client_data(sock)

    def _ipc_handle_client_data(self, client: socket.socket) -> None:
        """Read and dispatch data from a connected client."""
        try:
            data = client.recv(65536)
            if not data:
                self._ipc_remove_client(client)
                return

            for line in data.decode("utf-8", errors="replace").strip().split("\n"):
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    topic = msg["topic"]
                    value = msg.get("value")
                    ts = msg.get("ts", time.time())

                    # Dispatch locally
                    with self._lock:
                        self._last_values[topic] = (value, ts)
                        callbacks = list(self._subscribers.get(topic, []))
                        wildcards = list(self._wildcard_subscribers)

                    for cb in callbacks + wildcards:
                        try:
                            cb(topic, value, ts)
                        except Exception:
                            log.exception("IPC dispatch error for '%s'", topic)

                    # Relay to other clients (not the sender)
                    self._ipc_broadcast(topic, value, ts, exclude=client)

                except (json.JSONDecodeError, KeyError) as e:
                    log.warning("IPC: invalid message: %s", e)

        except OSError:
            self._ipc_remove_client(client)

    def _ipc_remove_client(self, client: socket.socket) -> None:
        """Remove a disconnected client."""
        with self._ipc_clients_lock:
            try:
                self._ipc_clients.remove(client)
            except ValueError:
                pass
        try:
            client.close()
        except OSError:
            pass
        log.info("IPC client disconnected")

    def _ipc_broadcast(self, topic: str, value: Any, timestamp: float,
                       exclude: Optional[socket.socket] = None) -> None:
        """Send an event to all connected IPC clients."""
        try:
            payload = json.dumps({
                "topic": topic, "value": value, "ts": timestamp,
            }, default=str) + "\n"
        except (TypeError, ValueError):
            return

        data = payload.encode("utf-8")
        dead = []

        with self._ipc_clients_lock:
            for client in self._ipc_clients:
                if client is exclude:
                    continue
                try:
                    client.sendall(data)
                except OSError:
                    dead.append(client)

        for client in dead:
            self._ipc_remove_client(client)

    # ------------------------------------------------------------------
    # IPC Client (run by secondary services)
    # ------------------------------------------------------------------

    def connect_ipc(self, socket_path: str = DEFAULT_SOCKET_PATH,
                    timeout: float = 10.0) -> bool:
        """Connect to the IPC server as a client.

        Args:
            socket_path: Path to the server's Unix socket.
            timeout: Connection timeout in seconds.

        Returns:
            True if connected successfully.
        """
        self._ipc_client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._ipc_client_sock.settimeout(timeout)

        try:
            self._ipc_client_sock.connect(socket_path)
            self._ipc_client_sock.setblocking(False)
            self._ipc_running = True

            thread = threading.Thread(target=self._ipc_client_loop, daemon=True)
            thread.start()
            log.info("IPC client connected to %s", socket_path)
            return True

        except OSError as e:
            log.warning("IPC connect failed: %s", e)
            self._ipc_client_sock = None
            return False

    def disconnect_ipc(self) -> None:
        """Disconnect from the IPC server."""
        self._ipc_running = False
        if self._ipc_client_sock:
            try:
                self._ipc_client_sock.close()
            except OSError:
                pass
            self._ipc_client_sock = None
            log.info("IPC client disconnected")

    def _ipc_client_loop(self) -> None:
        """Receive events from the IPC server."""
        buf = ""
        while self._ipc_running:
            sock = self._ipc_client_sock
            if sock is None:
                break
            try:
                ready, _, _ = select.select([sock], [], [], 0.5)
            except (ValueError, OSError):
                break

            if not ready:
                continue

            sock = self._ipc_client_sock
            if sock is None:
                break
            try:
                data = sock.recv(65536)
                if not data:
                    log.warning("IPC server closed connection")
                    break

                buf += data.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        topic = msg["topic"]
                        value = msg.get("value")
                        ts = msg.get("ts", time.time())

                        # Dispatch locally (without re-sending to server)
                        with self._lock:
                            self._last_values[topic] = (value, ts)
                            callbacks = list(self._subscribers.get(topic, []))
                            wildcards = list(self._wildcard_subscribers)

                        for cb in callbacks + wildcards:
                            try:
                                cb(topic, value, ts)
                            except Exception:
                                log.exception("IPC client dispatch error for '%s'", topic)

                    except (json.JSONDecodeError, KeyError) as e:
                        log.warning("IPC client: invalid message: %s", e)

            except OSError:
                break

        self._ipc_client_sock = None

    def _ipc_send(self, topic: str, value: Any, timestamp: float) -> None:
        """Send an event to the IPC server."""
        if not self._ipc_client_sock:
            return
        try:
            payload = json.dumps({
                "topic": topic, "value": value, "ts": timestamp,
            }, default=str) + "\n"
            self._ipc_client_sock.sendall(payload.encode("utf-8"))
        except OSError:
            log.warning("IPC send failed — server may be down")
            self._ipc_client_sock = None
