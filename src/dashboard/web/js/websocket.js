/**
 * WebSocket client for real-time event bus data.
 * Connects to /ws for data streaming and /ws/input for keyboard input forwarding.
 */

const DataStore = (() => {
    let _data = {};
    const _subscribers = {};
    let _dataWs = null;
    let _inputWs = null;
    let _reconnectDelay = 1000;
    let _connected = false;
    // HTTP fallback for AA touches (see sendAATouch): one request at a time,
    // in order, and never more than a handful queued.
    const AA_HTTP_MAX_PENDING = 8;
    let _aaHttpChain = Promise.resolve();
    let _aaHttpPending = 0;

    function connectData() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        _dataWs = new WebSocket(`${proto}//${location.host}/ws`);

        _dataWs.onopen = () => {
            _connected = true;
            _reconnectDelay = 1000;
            document.body.classList.remove("ws-disconnected");
            _notify("_connection", true);
        };

        _dataWs.onmessage = (e) => {
            try {
                const newData = JSON.parse(e.data);
                const changed = [];
                for (const [key, val] of Object.entries(newData)) {
                    if (_data[key] !== val) {
                        changed.push(key);
                    }
                    _data[key] = val;
                }
                // Notify subscribers of changed fields
                for (const key of changed) {
                    _notify(key, _data[key]);
                }
                // Always notify global subscribers
                _notify("*", _data);
            } catch (err) {
                // ignore parse errors
            }
        };

        _dataWs.onclose = () => {
            _connected = false;
            document.body.classList.add("ws-disconnected");
            _notify("_connection", false);
            setTimeout(connectData, Math.min(_reconnectDelay, 8000));
            _reconnectDelay *= 1.5;
        };

        _dataWs.onerror = () => {
            _dataWs.close();
        };
    }

    function connectInput() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        _inputWs = new WebSocket(`${proto}//${location.host}/ws/input`);

        _inputWs.onclose = () => {
            setTimeout(connectInput, 2000);
        };
        _inputWs.onerror = () => {
            _inputWs.close();
        };
    }

    function _notify(key, value) {
        const cbs = _subscribers[key];
        if (cbs) {
            for (const cb of cbs) {
                try { cb(value, key); } catch (e) { /* ignore */ }
            }
        }
    }

    return {
        /** Initialize WebSocket connections */
        init() {
            connectData();
            connectInput();
        },

        /** Get current value for a data field */
        get(key, defaultVal) {
            return _data[key] !== undefined ? _data[key] : defaultVal;
        },

        /** Get all current data */
        getAll() {
            return { ..._data };
        },

        /** Subscribe to changes on a specific field. Use "*" for all updates. */
        subscribe(key, callback) {
            if (!_subscribers[key]) _subscribers[key] = [];
            _subscribers[key].push(callback);
        },

        /** Unsubscribe a callback */
        unsubscribe(key, callback) {
            const cbs = _subscribers[key];
            if (cbs) {
                const idx = cbs.indexOf(callback);
                if (idx !== -1) cbs.splice(idx, 1);
            }
        },

        /** Send a keyboard event to the backend */
        sendKey(key) {
            if (_inputWs && _inputWs.readyState === WebSocket.OPEN) {
                _inputWs.send(JSON.stringify({ type: "keydown", key }));
            }
        },

        /**
         * Send an Android Auto touch event (A2 overlay → xdotool on :99).
         * action: "down" | "move" | "up" | "cancel" | "tap"; x, y: 0..1
         * relative to the AA canvas (null for cancel).
         *
         * Normally rides the ordered /ws/input socket. While it is down,
         * tap/down/up/cancel fall back to POST /aa/touch — chained so they
         * reach the server in order (a reordered down/up would leave the
         * AA finger pressed) and bounded. Moves are never sent over HTTP:
         * that would be one request per frame; the drag simply resumes
         * once the socket is back.
         */
        sendAATouch(action, x, y) {
            const msg = { type: "aa_touch", action, x, y };
            if (_inputWs && _inputWs.readyState === WebSocket.OPEN) {
                try {
                    _inputWs.send(JSON.stringify(msg));
                    return true;
                } catch (e) { /* fall through to HTTP */ }
            }
            if (action === "move") return false;
            if (_aaHttpPending >= AA_HTTP_MAX_PENDING) return false;
            _aaHttpPending++;
            let timer = null;
            // .catch before .finally: a failed (or throwing) request must
            // never leave the chain rejected, or every later touch is lost.
            _aaHttpChain = _aaHttpChain.then(() => {
                const ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
                if (ctl) timer = setTimeout(() => ctl.abort(), 2000);
                return fetch("/aa/touch", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ action, x, y }),
                    signal: ctl ? ctl.signal : undefined,
                });
            }).catch(() => {}).finally(() => {
                if (timer) clearTimeout(timer);
                _aaHttpPending--;
            });
            return true;
        },

        /** Check if WebSocket is connected */
        isConnected() {
            return _connected;
        },
    };
})();
