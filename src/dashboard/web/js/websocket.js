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

        /** Check if WebSocket is connected */
        isConnected() {
            return _connected;
        },
    };
})();
