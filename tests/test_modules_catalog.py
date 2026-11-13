"""Module toggles and their dependencies (src/core/modules_catalog.py), the
start path in main.py and Settings → Moduły (GET/POST /api/modules).

Cross-cutting requirement of the plan (sections C–I): every additional
feature has its own ``modules.<name>`` toggle, off in code and in the
production config; a module whose dependencies are off logs ONE warning and
does nothing; the UI warns before such a toggle is saved and enables the
dependencies only on an explicit request (``with_deps``).

Nothing is started for real: the graph functions are pure, main.py's module
entry points are replaced by spies, and the web routes run through Flask's
test client with ``cfg.save`` stubbed.
"""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from src.core import modules_catalog as mc
from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.dashboard import web_viewer as wv
from src.dashboard.web_viewer import WebViewer

REPO = Path(__file__).resolve().parent.parent

#: Toggles registered for plan sections C–I.
NEW_TOGGLES = ("car_phone", "car_phone_hotspot", "phone_sensors", "auto_brightness",
               "crash_sms", "call112", "car_phone_agent", "parking_guard",
               "cabin_watch", "remote_session")
#: ... of which these have code now (plan C + D1/D2: src/network/car_phone.py,
#: D3: src/sensors/phone_sensors.py).
IMPLEMENTED = ("car_phone", "car_phone_hotspot", "phone_sensors")
#: ... and these are still planned (listed, never started).
PLANNED = tuple(n for n in NEW_TOGGLES if n not in IMPLEMENTED)


def _cfg(name="bcm_config.yaml", **toggles):
    cfg = BCMConfig(config_path=str(REPO / "config" / name), platform_override="x86",
                    local_path=None, env={})
    for key, value in toggles.items():
        cfg.set(f"modules.{key}", value)
    return cfg


def _cat(**entries):
    """A synthetic catalog: name -> requires (tuple) / dict of extra keys."""
    out = {}
    for name, spec in entries.items():
        info = {"part": 1, "description": name, "default": False}
        if isinstance(spec, dict):
            info.update(spec)
        elif spec:
            info["requires"] = spec
        out[name] = info
    return out


# ── the shipped catalog ──────────────────────────────────────────────────

class TestShippedCatalog:
    @pytest.mark.parametrize("name", NEW_TOGGLES)
    def test_new_toggle_defaults_off_and_is_listed_honestly(self, name):
        info = mc.MODULES[name]
        assert info["default"] is False
        if name in PLANNED:
            assert info.get("planned") is True and "entry" not in info
        else:
            assert not info.get("planned")
        assert info.get("hardware"), "Settings shows what has to be plugged in"
        assert info.get("group") in ("telefon_w_aucie", "bezpieczenstwo", "zasilanie")

    def test_implemented_entries(self):
        assert mc.MODULES["car_phone"]["entry"] == ("src.network.car_phone", "start_car_phone")
        # read inside car_phone, no start path of its own
        assert "entry" not in mc.MODULES["car_phone_hotspot"]
        assert mc.MODULES["phone_sensors"]["entry"] == ("src.sensors.phone_sensors",
                                                        "start_phone_sensors")

    @pytest.mark.parametrize("cfg_name", ["bcm_config.yaml", "bcm_config_test.yaml"])
    @pytest.mark.parametrize("name", NEW_TOGGLES)
    def test_new_toggles_are_off_in_both_configs(self, cfg_name, name):
        cfg = _cfg(cfg_name)
        assert mc.is_enabled(cfg, name) is False
        assert mc.module_states(cfg)[name].runs is False

    def test_existing_modules_keep_their_place(self):
        # moved to src/safety (plan F); src/camera/crash_detect.py is a wrapper
        assert mc.MODULES["crash_detect"]["entry"] == ("src.safety.crash_detect",
                                                       "start_crash_detect")
        assert mc.MODULES["crash_detect"]["requires"] == ("location",)
        assert mc.MODULES["phone_status"]["default"] is False
        for name in ("phonebook", "phone_status", "phone_tether"):
            assert mc.MODULES[name]["requires"] == ("bluetooth",), name

    def test_graph_is_sound(self):
        assert mc.find_cycles(mc.MODULES) == set()
        for name, info in mc.MODULES.items():
            for group in mc.requirement_groups(info):
                for dep in group:
                    assert dep in mc.MODULES, f"{name} requires unknown {dep}"
                    assert dep != name

    def test_planned_dependencies_follow_the_plan(self):
        groups = {n: mc.requirement_groups(mc.MODULES[n]) for n in NEW_TOGGLES}
        assert groups["car_phone"] == ()
        for name in ("car_phone_hotspot", "phone_sensors", "car_phone_agent"):
            assert groups[name] == (("car_phone",),)
        for name in ("parking_guard", "cabin_watch"):
            assert groups[name] == (("car_phone_agent",),)
        assert set(groups["crash_sms"]) == {("crash_detect",), ("phone_sensors",),
                                            ("car_phone_agent",)}
        assert ("car_phone_agent", "bluetooth") in groups["call112"]
        assert ("phone_sensors", "input") in groups["auto_brightness"]

    def test_production_starts_exactly_what_it_did(self):
        states = mc.module_states(_cfg())
        assert sorted(n for n, st in states.items() if st.runs) == sorted(
            ["dashboard", "weather", "route_planner", "multimedia", "bluetooth", "wifi_ap",
             "input", "audio"])
        assert all(st.reason in (mc.REASON_OK, mc.REASON_DISABLED) for st in states.values())


# ── pure graph functions ─────────────────────────────────────────────────

class TestResolve:
    def test_missing_dependency_blocks(self):
        cat = _cat(a=None, b=("a",))
        st = mc.resolve(cat, {"b": True})
        assert st["b"].runs is False and st["b"].reason == mc.REASON_MISSING_DEPS
        assert st["b"].blocked_by == (("a",),)
        assert mc.resolve(cat, {"a": True, "b": True})["b"].runs is True

    def test_transitive_and_off_modules_still_report_blockers(self):
        cat = _cat(a=None, b=("a",), c=("b",))
        st = mc.resolve(cat, {"b": True, "c": True})
        assert not st["b"].runs and not st["c"].runs
        assert st["c"].blocked_by == (("b",),)          # b is on but does not run
        off = mc.resolve(cat, {})["c"]
        assert off.reason == mc.REASON_DISABLED and off.blocked_by == (("b",),)

    def test_any_of_group(self):
        cat = _cat(p=None, i=None, x={"requires_any": (("p", "i"),)})
        assert mc.resolve(cat, {"x": True, "i": True})["x"].runs
        assert mc.resolve(cat, {"x": True, "p": True})["x"].runs
        st = mc.resolve(cat, {"x": True})["x"]
        assert not st.runs and st.blocked_by == (("p", "i"),)

    def test_unknown_name_blocks_instead_of_being_ignored(self):
        cat = _cat(a=("typo",))
        st = mc.resolve(cat, {"a": True})["a"]
        assert not st.runs and st.blocked_by == (("typo",),)
        assert "typo (unknown module)" in mc.block_message(st, cat)

    def test_planned_never_runs(self):
        cat = _cat(a={"planned": True}, b=("a",))
        st = mc.resolve(cat, {"a": True, "b": True})
        assert st["a"].reason == mc.REASON_UNAVAILABLE and not st["a"].available
        assert not st["b"].runs and st["b"].reason == mc.REASON_MISSING_DEPS

    def test_cycle_guard_terminates(self):
        cat = _cat(p=("q",), q=("r",), r=("p",), s=("s",), ok=None, dep=("p",))
        assert mc.find_cycles(cat) == {"p", "q", "r", "s"}
        st = mc.resolve(cat, dict.fromkeys(cat, True))
        for name in ("p", "q", "r", "s"):
            assert not st[name].runs and st[name].reason == mc.REASON_CYCLE
        assert st["ok"].runs and not st["dep"].runs
        assert mc.enable_plan(cat, {}, "p") is None
        assert mc.enable_plan(cat, {}, "dep") is None
        assert "cycle" in mc.block_message(st["p"], cat)

    def test_requirement_groups_tolerate_a_bare_string(self):
        assert mc.requirement_groups({"requires": "bluetooth"}) == (("bluetooth",),)
        assert mc.requirement_groups({"requires_any": ["ab", ("c", "d"), ()]}) == \
            (("ab",), ("c", "d"))
        assert mc.requirement_groups({}) == ()


class TestEnablePlan:
    def test_dependencies_first_without_duplicates(self):
        cat = _cat(base=None, mid=("base",), side=("base",), top=("mid", "side"))
        assert mc.enable_plan(cat, {}, "top") == ["base", "mid", "side"]
        assert mc.enable_plan(cat, {"base": True}, "top") == ["mid", "side"]
        assert mc.enable_plan(cat, {"base": True, "mid": True, "side": True}, "top") == []

    def test_enabled_but_blocked_dependency_brings_its_own(self):
        cat = _cat(base=None, mid=("base",), top=("mid",))
        assert mc.enable_plan(cat, {"mid": True}, "top") == ["base"]

    def test_any_of_prefers_a_running_member_then_the_first_available(self):
        cat = _cat(p={"planned": True}, i=None, j=None, x={"requires_any": (("p", "i", "j"),)})
        assert mc.enable_plan(cat, {"j": True}, "x") == []
        assert mc.enable_plan(cat, {}, "x") == ["i"]       # p is planned: skipped

    def test_impossible(self):
        cat = _cat(p={"planned": True}, x=("p",), y=("nope",), z={"planned": True})
        assert mc.enable_plan(cat, {}, "x") is None
        assert mc.enable_plan(cat, {}, "y") is None
        assert mc.enable_plan(cat, {}, "z") is None
        assert mc.enable_plan(cat, {}, "missing") is None

    def test_real_catalog(self):
        cfg = _cfg(bluetooth=False)
        assert mc.enable_plan(mc.MODULES, mc.enabled_map(cfg), "phone_status") == ["bluetooth"]
        # every C–I module needs something planned: nothing to offer yet
        assert mc.enable_plan(mc.MODULES, mc.enabled_map(cfg), "crash_sms") is None

    def test_would_stop(self):
        cat = _cat(bt=None, pb=("bt",), ps=("pb",), other=None)
        on = dict.fromkeys(cat, True)
        assert mc.would_stop(cat, on, "bt") == ["pb", "ps"]
        assert mc.would_stop(cat, on, "other") == []


class TestBlockMessage:
    def test_variants(self):
        cat = _cat(a=None, b={"requires": ("a",), "requires_any": (("x", "a"),)},
                   x={"planned": True})
        st = mc.resolve(cat, {"b": True, "x": True})
        assert mc.block_message(st["b"], cat).startswith(
            "Module b not started: missing dependency a, x or a")
        assert "not available in this version" in mc.block_message(st["x"], cat)
        assert mc.block_message(mc.resolve(cat, {})["b"], cat) == ""        # off
        assert mc.block_message(mc.resolve(cat, {"a": True})["a"], cat) == ""   # runs

    # car_phone -> car_phone_agent -> parking_guard: once car_phone lands this
    # is the normal case for crash_sms / parking_guard / cabin_watch.
    CHAIN = _cat(car_phone=None, car_phone_agent=("car_phone",),
                 parking_guard=("car_phone_agent",), deep=("parking_guard",))

    def test_enabled_but_blocked_dependency_is_not_called_off(self):
        on = {"car_phone_agent": True, "parking_guard": True, "deep": True}
        st = mc.resolve(self.CHAIN, on)
        msg = mc.block_message(st["parking_guard"], self.CHAIN, st)
        assert msg.startswith("Module parking_guard not started: missing dependency "
                              "car_phone_agent (enabled, but not running); the cause: car_phone ")
        assert "Settings → Moduły" in msg
        # deeper chains point at the same root, once
        assert mc.block_message(st["deep"], self.CHAIN, st) == (
            "Module deep not started: missing dependency parking_guard (enabled, but not "
            "running); the cause: car_phone (enable it in Settings → Moduły / modules.* "
            "in local.yaml)")
        # the direct case is unchanged
        assert mc.block_message(st["car_phone_agent"], self.CHAIN, st).startswith(
            "Module car_phone_agent not started: missing dependency car_phone (enable it")
        # without the map the old wording stays (callers that have no states)
        assert "the cause" not in mc.block_message(st["parking_guard"], self.CHAIN)

    def test_root_blockers(self):
        on = {"car_phone_agent": True, "parking_guard": True, "deep": True}
        st = mc.resolve(self.CHAIN, on)
        assert mc.root_blockers(st, "deep") == ["car_phone"]
        assert mc.root_blockers(st, "car_phone_agent") == ["car_phone"]
        assert mc.root_blockers(mc.resolve(self.CHAIN, {"deep": True}), "deep") == ["parking_guard"]
        cat = _cat(p=("q",), q=("p",), x=("p",), u=("typo",), w=("u",))
        st = mc.resolve(cat, dict.fromkeys(cat, True))
        assert mc.root_blockers(st, "x") == ["p"]          # cycle: stops, no loop
        assert mc.root_blockers(st, "w") == ["typo"]
        assert mc.root_blockers({}, "nope") == []

    def test_root_that_cannot_be_enabled_is_not_sent_to_settings(self):
        cat = _cat(pl={"planned": True}, mid=("pl",), top=("mid",))
        for on in ({"mid": True, "top": True}, {"pl": True, "mid": True, "top": True}):
            st = mc.resolve(cat, on)
            msg = mc.block_message(st["top"], cat, st)
            assert msg == ("Module top not started: missing dependency mid (enabled, but not "
                           "running); the cause: pl (not available in this version)"), msg
            msg = mc.block_message(st["mid"], cat, st)
            assert msg == ("Module mid not started: missing dependency pl "
                           "(not available in this version)"), msg

    def test_main_reports_with_the_whole_map(self, monkeypatch, caplog):
        monkeypatch.setattr(mc, "MODULES", self.CHAIN)
        st = mc.resolve(self.CHAIN, {"car_phone_agent": True, "parking_guard": True})
        log = logging.getLogger("bcm.main.test")
        with caplog.at_level(logging.WARNING, logger="bcm.main.test"):
            assert main.report_blocked_modules(st, log) == 2
        msgs = sorted(r.getMessage() for r in caplog.records if r.name == "bcm.main.test")
        assert "car_phone_agent (enabled, but not running); the cause: car_phone" in msgs[1]


# ── main.py start path ───────────────────────────────────────────────────

@pytest.fixture
def spies(monkeypatch):
    """Every registry entry point replaced by a recorder (nothing imported)."""
    calls = []
    registry = {}
    for name, info in main.MODULE_REGISTRY.items():
        def start(*args, _name=name, **kwargs):
            calls.append(_name)
        registry[name] = dict(info, start=start)
    monkeypatch.setattr(main, "MODULE_REGISTRY", registry)
    return calls


def _start(cfg, cli=None):
    states = main.plan_modules(cfg, cli)
    main.start_modules(main.registry_to_start(states), cfg, EventBus(), hal=None)
    return states


class TestMainStartPath:
    def test_disabled_module_entry_is_never_called(self, spies):
        cfg = _cfg(**{name: False for name in main.MODULE_REGISTRY})
        _start(cfg)
        assert spies == []

    def test_production_starts_the_same_registry_modules(self, spies):
        _start(_cfg())
        assert sorted(spies) == ["audio", "input", "multimedia", "weather"]

    def test_missing_dependency_is_not_started_and_warned_once(self, spies, caplog):
        cfg = _cfg("bcm_config_test.yaml", bluetooth=False)
        states = _start(cfg)
        assert "phone_tether" not in spies and "weather" in spies
        log = logging.getLogger("bcm.main.test")
        with caplog.at_level(logging.WARNING, logger="bcm.main.test"):
            assert main.report_blocked_modules(states, log) == 3
        msgs = [r.getMessage() for r in caplog.records if r.name == "bcm.main.test"]
        assert len(msgs) == 3, msgs
        for name in ("phone_tether", "phonebook", "phone_status"):
            hits = [m for m in msgs if m.startswith(f"Module {name} not started")]
            assert len(hits) == 1 and "missing dependency bluetooth" in hits[0], msgs

    def test_planned_module_switched_on_is_reported_not_started(self, spies, caplog):
        cfg = _cfg(car_phone_agent=True, crash_sms=True)
        states = _start(cfg)
        assert not states["car_phone_agent"].runs and not states["crash_sms"].runs
        log = logging.getLogger("bcm.main.test")
        with caplog.at_level(logging.WARNING, logger="bcm.main.test"):
            assert main.report_blocked_modules(states, log) == 2
        recs = [r.getMessage() for r in caplog.records if r.name == "bcm.main.test"]
        assert len(recs) == 2 and all("not available in this version" in m for m in recs), recs
        assert not any(n in spies for n in NEW_TOGGLES)

    def test_car_phone_switched_on_starts_and_hotspot_follows_it(self, spies):
        states = _start(_cfg(car_phone=True, car_phone_hotspot=True))
        assert "car_phone" in spies
        assert states["car_phone_hotspot"].runs is True
        states = _start(_cfg(car_phone_hotspot=True))
        assert states["car_phone_hotspot"].runs is False
        assert states["car_phone_hotspot"].blocked_by == (("car_phone",),)

    def test_cli_modules_decide_registry_modules(self, spies):
        cfg = _cfg("bcm_config_test.yaml")
        states = _start(cfg, ["weather", "phone_tether", "typo"])
        assert sorted(spies) == ["phone_tether", "weather"]
        assert states["dashboard"].runs is False
        assert states["bluetooth"].runs is True          # subsystems keep their toggle

    def test_subsystem_gates_use_the_dependency_check(self):
        text = (REPO / "main.py").read_text(encoding="utf-8")
        for name in ("phonebook", "phone_status", "fuel_sender", "route_planner",
                     "small_display"):
            assert f'_runs("{name}")' in text, name
        assert "bt_enabled = _runs(\"bluetooth\")" in text
        assert "modules_catalog.is_enabled(config" not in text


# ── GET/POST /api/modules ────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_web_subprocess(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError("no subprocess from the modules routes")
    monkeypatch.setattr(wv, "subprocess", SimpleNamespace(run=refuse, Popen=refuse))


def _web(cfg):
    saved = []
    cfg.save = lambda path=None: saved.append(True) or True
    bus = EventBus()
    events = []
    bus.subscribe("config.changed", lambda t, v, ts: events.append(v))
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=cfg)
    return SimpleNamespace(cfg=cfg, client=viewer._build_app().test_client(), saved=saved,
                           events=events, viewer=viewer)


def _by_name(payload):
    return {m["name"]: m for m in payload["modules"]}


class TestModulesApi:
    def test_get_payload(self):
        web = _web(_cfg("bcm_config_test.yaml"))
        res = web.client.get("/api/modules")
        assert res.status_code == 200
        body = res.get_json()
        assert body["restart_required"] is False
        mods = _by_name(body)
        assert set(mods) == set(mc.MODULES)
        for m in mods.values():
            for key in ("requires", "requires_any", "hardware", "available", "blocked_by",
                        "needs", "would_stop", "runs", "reason", "group", "restart_pending"):
                assert key in m, (m["name"], key)
            assert m["restart_pending"] is False
        car = mods["car_phone"]
        assert car["available"] is True and car["kind"] == "module" and car["enabled"] is False
        assert car["hardware"].startswith("Redmi")
        assert mods["car_phone_hotspot"]["kind"] == "subsystem"
        assert mods["car_phone_hotspot"]["needs"] == ["car_phone"]
        assert mods["car_phone_agent"]["available"] is False
        sensors = mods["phone_sensors"]
        assert sensors["available"] is True and sensors["kind"] == "module"
        assert sensors["needs"] == ["car_phone"] and sensors["runs"] is False
        assert mods["crash_detect"]["requires"] == ["location"]
        # crash_detect runs in the test config (GPS-only path, plan F)
        assert mods["crash_detect"]["runs"] is True
        assert mods["crash_sms"]["blocked_by"] == [["phone_sensors"], ["car_phone_agent"]]
        assert mods["crash_sms"]["needs"] is None
        assert mods["auto_brightness"]["requires_any"] == [["phone_sensors", "input"]]
        assert mods["phone_status"]["requires"] == ["bluetooth"]
        assert mods["phone_status"]["runs"] is True
        assert mods["bluetooth"]["would_stop"] == ["phone_tether", "phonebook", "phone_status"]

    @pytest.mark.parametrize("body", [
        None, [], "weather", {"name": "nope", "enabled": True},
        {"name": ["weather"], "enabled": True}, {"enabled": True},
        {"name": "weather"}, {"name": "weather", "enabled": "false"},
        {"name": "weather", "enabled": 1}, {"name": "weather", "enabled": None},
        {"name": "weather", "enabled": True, "with_deps": "yes"},
    ])
    def test_post_validates_names_and_booleans(self, body):
        web = _web(_cfg())
        before = web.cfg.get("modules.weather")
        res = web.client.post("/api/modules", json=body)
        assert res.status_code == 400
        assert web.cfg.get("modules.weather") == before
        assert web.saved == [] and web.events == []

    def test_post_saves_and_says_when_a_restart_is_needed(self):
        web = _web(_cfg())
        res = web.client.post("/api/modules", json={"name": "weather", "enabled": False})
        body = res.get_json()
        assert res.status_code == 200 and body["ok"] is True and body["persisted"] is True
        assert web.cfg.get("modules.weather") is False and web.saved == [True]
        assert body["restart_required"] is True and body["runs"] is False
        assert _by_name(body)["weather"]["restart_pending"] is True
        assert web.events[-1] == {"module": "weather", "enabled": False, "also": []}
        # back to what is running: nothing left to restart for
        body = web.client.post("/api/modules", json={"name": "weather", "enabled": True}).get_json()
        assert body["restart_required"] is False
        assert web.client.get("/api/modules").get_json()["restart_required"] is False

    def test_planned_module_cannot_be_switched_on(self):
        web = _web(_cfg())
        res = web.client.post("/api/modules", json={"name": "car_phone_agent", "enabled": True})
        assert res.status_code == 409 and res.get_json()["available"] is False
        assert web.cfg.get("modules.car_phone_agent") is None and web.saved == []
        # ... but one switched on by hand can be switched off
        web.cfg.set("modules.car_phone_agent", True)
        res = web.client.post("/api/modules", json={"name": "car_phone_agent", "enabled": False})
        assert res.status_code == 200
        assert web.cfg.get("modules.car_phone_agent") is False
        assert res.get_json()["restart_required"] is False      # it never ran

    def test_car_phone_can_be_switched_on(self):
        web = _web(_cfg())
        res = web.client.post("/api/modules", json={"name": "car_phone", "enabled": True})
        assert res.status_code == 200 and res.get_json()["runs"] is True
        assert web.cfg.get("modules.car_phone") is True and web.saved == [True]
        assert res.get_json()["restart_required"] is True

    def test_phone_sensors_can_be_switched_on_with_car_phone(self):
        web = _web(_cfg())
        body = web.client.post("/api/modules", json={"name": "phone_sensors", "enabled": True,
                                                     "with_deps": True}).get_json()
        assert body["enabled_also"] == ["car_phone"] and body["runs"] is True
        assert web.cfg.get("modules.phone_sensors") is True
        assert web.cfg.get("modules.car_phone") is True and web.saved == [True]

    def test_enable_without_dependencies_is_saved_alone(self):
        web = _web(_cfg("bcm_config_test.yaml", bluetooth=False))
        body = web.client.post("/api/modules",
                               json={"name": "phone_status", "enabled": True}).get_json()
        assert web.cfg.get("modules.bluetooth") is False          # no silent cascade
        assert body["enabled_also"] == [] and body["runs"] is False
        assert body["blocked_by"] == [["bluetooth"]]

    def test_enable_with_deps_on_request(self):
        web = _web(_cfg("bcm_config_test.yaml", bluetooth=False, phone_status=False))
        body = web.client.post("/api/modules", json={"name": "phone_status", "enabled": True,
                                                     "with_deps": True}).get_json()
        assert body["enabled_also"] == ["bluetooth"] and body["runs"] is True
        assert web.cfg.get("modules.bluetooth") is True
        assert web.cfg.get("bluetooth.enabled") is True          # legacy key in step
        assert web.cfg.get("modules.phone_status") is True
        assert web.saved == [True]                               # one save for all
        assert web.events[-1]["also"] == ["bluetooth"]
        assert body["restart_required"] is True

    def test_with_deps_that_cannot_be_enabled_is_refused(self, monkeypatch):
        cat = dict(mc.MODULES)
        cat["needs_planned"] = {"part": 1, "description": "x", "default": False,
                                "requires": ("car_phone_agent",)}
        monkeypatch.setattr(mc, "MODULES", cat)
        web = _web(_cfg())
        res = web.client.post("/api/modules", json={"name": "needs_planned", "enabled": True,
                                                    "with_deps": True})
        assert res.status_code == 409
        assert web.cfg.get("modules.needs_planned") is None and web.saved == []
        # without with_deps it is saved (and would log its one warning)
        res = web.client.post("/api/modules", json={"name": "needs_planned", "enabled": True})
        assert res.status_code == 200 and res.get_json()["blocked_by"] == [["car_phone_agent"]]

    def test_save_failure_is_reported_not_500(self):
        web = _web(_cfg())
        def boom(path=None):
            raise OSError("read-only")
        web.cfg.save = boom
        res = web.client.post("/api/modules", json={"name": "weather", "enabled": False})
        assert res.status_code == 200 and res.get_json()["persisted"] is False

    def test_restart_baseline_is_what_main_started(self):
        # main.py hands over what really started (e.g. --modules weather):
        # the config alone would say every enabled module runs.
        cfg = _cfg()
        cfg.save = lambda path=None: True
        boot = {name: name == "weather" for name in mc.MODULES}
        viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=EventBus(), config=cfg,
                           boot_module_runs=boot)
        body = viewer._build_app().test_client().get("/api/modules").get_json()
        mods = _by_name(body)
        assert mods["weather"]["restart_pending"] is False
        assert mods["bluetooth"]["restart_pending"] is True       # on in config, not started
        assert body["restart_required"] is True
        # without it: recomputed from the config (nothing pending right after start)
        assert _web(_cfg()).client.get("/api/modules").get_json()["restart_required"] is False

    def test_main_passes_the_boot_runs(self):
        text = (REPO / "main.py").read_text(encoding="utf-8")
        assert "boot_module_runs={n: st.runs for n, st in module_states.items()}" in text

    def test_without_config(self):
        viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=EventBus(), config=None)
        client = viewer._build_app().test_client()
        assert client.get("/api/modules").get_json() == {"modules": [],
                                                         "restart_required": False}
        assert client.post("/api/modules", json={"name": "weather",
                                                 "enabled": True}).status_code == 500
