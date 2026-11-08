"""Dashboard notifications: the backend publisher (src/core/notifications.py)
and the kiosk toast logic (web/js/components/notifications.js, plain node)."""

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from src.core.event_bus import EventBus
from src.core.notifications import (
    MAX_ENTRIES,
    TOPIC,
    active_notifications,
    publish_notification,
)

ROOT = Path(__file__).resolve().parent.parent
NOTIF_JS = ROOT / "src" / "dashboard" / "web" / "js" / "components" / "notifications.js"


def _last(bus):
    last = bus.get_last(TOPIC)
    return last[0] if last else None


class TestPublisher:
    def test_entry_shape(self):
        bus = EventBus()
        entry = publish_notification(bus, "Brak mikrofonu", "opis", icon="mic_off",
                                     severity="warning", ttl=8, now=1000.0)
        assert _last(bus) == [entry]
        assert entry["title"] == "Brak mikrofonu" and entry["desc"] == "opis"
        assert entry["ts"] == 1000.0 and entry["ttl"] == 8.0
        assert isinstance(entry["id"], str) and entry["id"]

    def test_bounded_and_ids_unique(self):
        bus = EventBus()
        ids = {publish_notification(bus, f"n{i}", now=1000.0 + i)["id"] for i in range(20)}
        assert len(ids) == 20
        assert len(_last(bus)) == MAX_ENTRIES
        assert _last(bus)[-1]["title"] == "n19"

    def test_same_key_replaces(self):
        bus = EventBus()
        publish_notification(bus, "a", key="k", now=1000.0)
        publish_notification(bus, "b", now=1000.0)
        publish_notification(bus, "a2", key="k", now=1001.0)
        assert [e["title"] for e in _last(bus)] == ["b", "a2"]

    def test_expired_entries_are_dropped(self):
        bus = EventBus()
        publish_notification(bus, "old", ttl=1, now=1000.0)
        publish_notification(bus, "new", ttl=5, now=1010.0)
        assert [e["title"] for e in _last(bus)] == ["new"]
        assert active_notifications(_last(bus), now=1020.0) == []

    @pytest.mark.parametrize("value", [None, "x", 5, [1, "a", None], {"a": 1}])
    def test_active_notifications_never_raises(self, value):
        assert active_notifications(value, now=0) == []

    def test_untrusted_text_and_fields_are_sanitised(self):
        bus = EventBus()
        entry = publish_notification(bus, "A\x00B‮" + "x" * 500, "d\nd",
                                     severity="evil", icon="<img>", ttl="nan?", now=1.0)
        assert "\x00" not in entry["title"] and "‮" not in entry["title"]
        assert len(entry["title"]) <= 80
        assert entry["desc"] == "d d"
        assert entry["severity"] == "info" and entry["icon"] == "info"
        assert entry["ttl"] == 8.0

    def test_no_bus(self):
        assert publish_notification(None, "x") is None

    def test_concurrent_publishers_keep_every_entry(self):
        bus = EventBus()
        barrier = threading.Barrier(4)

        def worker(n):
            barrier.wait()
            publish_notification(bus, f"t{n}", key=f"k{n}")

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(e["title"] for e in _last(bus)) == ["t0", "t1", "t2", "t3"]


def _node():
    found = shutil.which("node")
    if found:
        return found
    for candidate in ("/opt/node22/bin/node", "/usr/local/bin/node"):
        if os.access(candidate, os.X_OK):
            return candidate
    return None


NODE = _node()

# Loads notifications.js in plain node, with a tiny DOM stub, and reports
# what the toast logic did. Text must land in textContent (never innerHTML).
_HARNESS = r"""
"use strict";
const path = process.argv[2];
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
function el(tag) {
  return { tag, id: "", style: {}, children: [], attrs: {}, textContent: "", className: "",
           get firstChild() { return this.children[0]; },
           appendChild(c) { c.parentNode = this; this.children.push(c); return c; },
           removeChild(c) { this.children.splice(this.children.indexOf(c), 1); c.parentNode = null; },
           setAttribute(k, v) { this.attrs[k] = v; },
           set innerHTML(v) { throw new Error("innerHTML used"); } };
}
const body = el("body");
const doc = {
  body, documentElement: body,
  createElement: el,
  getElementById(id) { return body.children.find((c) => c.id === id) || null; },
};
global.setTimeout = () => 0;
const N = require(path);
const out = { pending: N.pendingToasts(input.list, input.seen || []) .map((n) => n.id), shown: [] };
for (const batch of input.batches || []) {
  N.syncToasts(batch, doc);
  const host = doc.getElementById("bcm-toast-host");
  out.shown.push(host ? host.children.map((b) => b.children[1].children[0].textContent) : []);
}
const host = doc.getElementById("bcm-toast-host");
out.icon = host && host.children.length ? host.children[0].children[0].textContent : null;
out.pointer = host ? host.style.cssText.includes("pointer-events:none") : null;
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node not installed")
class TestToasts:
    def _run(self, payload, tmp_path):
        harness = tmp_path / "toast_harness.js"
        harness.write_text(_HARNESS)
        res = subprocess.run([NODE, str(harness), str(NOTIF_JS)], input=json.dumps(payload),
                             capture_output=True, text=True, timeout=60)
        assert res.returncode == 0, res.stderr
        return json.loads(res.stdout)

    def test_each_id_is_shown_once_with_text_content(self, tmp_path):
        a = {"id": "1-1", "title": "<b>Brak mikrofonu</b>", "icon": "mic_off",
             "severity": "warning", "ttl": 8}
        b = {"id": "1-2", "title": "Drugi", "icon": "x\"><script>", "ttl": 8}
        out = self._run({"list": [a, b, {"id": 3}, "junk"], "seen": ["1-2"],
                         "batches": [[a], [a], [a, b]]}, tmp_path)
        assert out["pending"] == ["1-1"]                      # seen / title-less skipped
        assert out["shown"] == [["<b>Brak mikrofonu</b>"],    # literal text, not HTML
                                ["<b>Brak mikrofonu</b>"],    # not shown twice
                                ["<b>Brak mikrofonu</b>", "Drugi"]]
        assert out["icon"] == "mic_off"
        assert out["pointer"] is True                         # touches pass through to AA

    def test_garbage_never_throws(self, tmp_path):
        out = self._run({"list": None, "batches": [None, "x", [None, 5, {}]]}, tmp_path)
        assert out["pending"] == [] and out["shown"] == [[], [], []]
