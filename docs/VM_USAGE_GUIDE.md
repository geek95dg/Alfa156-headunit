# BCM v8 — VM Usage Guide

How to run, navigate, and test the BCM headunit system inside a VM (VMware or similar).

> **Prerequisites:** VM already set up per [VMWARE_SETUP.md](VMWARE_SETUP.md).

---

## 1. Quick Start — HTML5 Frontend (Recommended)

The new HTML5/Tailwind frontend runs in your browser — no Pygame/X display needed.

```bash
cd ~/Alfa156-headunit
source .venv/bin/activate

# Start with HTML5 frontend (default)
./run_x86.sh

# Or explicitly:
python main.py --platform x86 --frontend
```

Then open your browser: **http://localhost:5002**

You'll see the Alfa Romeo head unit dashboard with:
- **3 switchable themes**: Heritage (amber/walnut), Modern (blue/white), Autodelta (orange/black)
- **5 screens**: Init → A1 Main → A2 Trip → A3 Weather → A4 Service
- **Live data**: simulated engine telemetry, fuel, weather, media
- **Interactive maps**: Leaflet.js on the Weather screen

### Keyboard controls (in browser)

| Key | Action |
|-----|--------|
| **LEFT/RIGHT** | Navigate between screens (A1 → A2 → A3 → A4) |
| **HOME** | Go to A1 Main screen |
| **ESC** | Back to dashboard from settings |

### Theme switching

Navigate to **Settings** (via the nav bar) and click a theme button, or use the `/api/config` REST endpoint:

```bash
# Switch to Autodelta theme
curl -X POST http://localhost:5002/api/config \
  -H "Content-Type: application/json" \
  -d '{"theme": "autodelta"}'
```

### REST API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/data` | GET | Current telemetry snapshot (JSON) |
| `/api/config` | GET | Current config (theme, language, units) |
| `/api/config` | POST | Update config `{"theme":"modern"}` |
| `/api/i18n/pl` | GET | Polish translation strings |
| `/api/i18n/en` | GET | English translation strings |

---

## 2. Starting the System

### Option A: HTML5 Frontend (default)

```bash
./run_x86.sh                    # Default — HTML5 frontend at :5002
./run_x86.sh --frontend         # Same, explicit
```

No X display or Pygame needed. Works headless, in SSH, in containers.

### Option B: Legacy Pygame Renderer

```bash
./run_x86.sh --pygame           # Opens Pygame window (800x480)
```

Requires X display (`$DISPLAY` set). The dashboard also streams to http://localhost:5002 as a frame viewer.

### Option C: Headless (backend only)

```bash
./run_x86.sh --headless         # Backend + web frontend, no Pygame
```

### Option D: Specific modules only

```bash
./run_x86.sh --modules obd,dashboard          # OBD + dashboard only
./run_x86.sh --pygame --modules obd,dashboard  # Pygame with specific modules
```

### Dry run

```bash
python main.py --platform x86 --dry-run
```

---

## 3. What You See in the Browser

### A1 Main (Heritage Theme)
- Left: Engine temperature gauge with amber glow and circular indicator
- Center: System Notifications (tire pressure, service alerts, route info)
- Right: Fuel level with progress bar and estimated range
- Bottom: Now Playing media + driving stats (Avg Speed, Drive Time, Voltage)

### A1 Main (Modern Theme)
- Light background with clean white cards
- Blue accent progress bars
- Notification Hub with pill badges
- Album art media player card

### A1 Main (Autodelta Theme)
- Pure black background, motorsport aesthetic
- Orange progress bars with glow effects
- Left panel: Coolant, Fuel, Oil Pressure gauges
- Status card + mini media player

### A2 Trip
- Trip statistics (distance, speed, time)
- Consumption bar chart (Heritage/Autodelta) or SVG line graph (Modern)
- Efficiency gauge, range remaining

### A3 Weather
- Live OpenStreetMap via Leaflet.js
- Current conditions, 3-day forecast
- GPS position marker (updated from event bus)
- Theme-specific map styling (amber/blue/grayscale tiles)

### A4 Service
- Vehicle diagnostics list (engine, tires, fluids, electrical)
- Car sketch image (Giulia GTA / 156 Berlina / 1600 Junior Z)
- TPMS pressure display
- Warning indicators with severity colors

### Initialization Screen
- Theme-specific boot sequence with car sketch breathing animation
- Progress bar, brand identity, system status text
- Auto-transitions to A1 after 4 seconds

---

## 4. Testing Demo Scenarios

### 4.1 Live data updates

Start the system — the demo data generator produces sinusoidal RPM, speed, coolant temp, and fuel data. Open http://localhost:5002 and watch values update in real-time (~15 FPS).

Verify with the REST API:
```bash
# See live data
curl -s http://localhost:5002/api/data | python3 -m json.tool
```

### 4.2 Theme switching

```bash
# Switch themes via API
curl -X POST http://localhost:5002/api/config -H "Content-Type: application/json" -d '{"theme":"heritage"}'
curl -X POST http://localhost:5002/api/config -H "Content-Type: application/json" -d '{"theme":"modern"}'
curl -X POST http://localhost:5002/api/config -H "Content-Type: application/json" -d '{"theme":"autodelta"}'
```

Or use the Settings screen in the browser.

### 4.3 Language switching

```bash
curl -X POST http://localhost:5002/api/config -H "Content-Type: application/json" -d '{"language":"en"}'
curl -X POST http://localhost:5002/api/config -H "Content-Type: application/json" -d '{"language":"pl"}'
```

### 4.4 Unit switching

```bash
# Switch to imperial
curl -X POST http://localhost:5002/api/config -H "Content-Type: application/json" -d '{"speed_unit":"mph","temp_unit":"F"}'

# Switch back to metric
curl -X POST http://localhost:5002/api/config -H "Content-Type: application/json" -d '{"speed_unit":"km/h","temp_unit":"C"}'
```

### 4.5 Multiple browser windows

Open the dashboard in multiple browser tabs or from different devices on the same network. All receive the same real-time data via WebSocket.

From another device: `http://<VM_IP>:5002`

---

## 5. Legacy Pygame Controls

When running with `--pygame`:

| Key | Action |
|-----|--------|
| **LEFT/RIGHT** | Navigate screens (A1→A2→A3→A4) |
| **UP/DOWN** | Adjust RPM (demo) |
| **HOME / H** | Open/close settings menu |
| **ESC** | Close settings or quit |
| **R** | Toggle reverse gear (camera + parking overlay) |
| **T** | Cycle exterior temperature |
| **I** | Trigger icing alert |
| **ENTER (hold 2s)** | Long press (reset trip / confirm service) |

---

## 6. Running Tests

```bash
cd ~/Alfa156-headunit
source .venv/bin/activate

# All tests
python -m pytest tests/ -v

# Specific module
python -m pytest tests/test_dashboard.py -v

# With coverage
python -m pytest tests/ --cov=src --cov-report=term-missing
```

---

## 7. Configuration

Edit `config/bcm_config.yaml`:

```yaml
display:
  dashboard:
    width: 800
    height: 480
    fps: 15
    theme: heritage      # heritage | modern | autodelta
    brightness: 70

language: pl             # pl | en

units:
  speed: km/h            # km/h | mph
  temperature: C         # C | F
```

---

## 8. Event Bus Debugging

```bash
# Watch all event bus messages
python3 -c "
from src.core.event_bus import EventBus
bus = EventBus()
bus.subscribe('*', lambda topic, value, ts: print(f'[{topic}] = {value}'))
import time
while True: time.sleep(1)
"
```

Common topics: `obd.rpm`, `obd.speed`, `obd.coolant_temp`, `obd.fuel_level`, `env.temperature`, `bt.media_title`, `gps.lat`, `gps.lon`, `weather.condition`

---

## 9. Accessing from Host Machine

If running in VMware with NAT networking:

1. Find VM IP: `ip addr show` (look for `192.168.x.x` or `10.x.x.x`)
2. From host browser: `http://<VM_IP>:5002`

If the host can't reach the VM, switch VMware network to **Bridged** mode.

---

## 10. Troubleshooting

### Frontend doesn't load
```bash
# Check Flask is running
curl http://localhost:5002/
# If 404/connection refused, check logs:
tail -f logs/bcm.log

# Ensure flask + flask-sock are installed
pip install flask flask-sock
```

### WebSocket disconnects repeatedly
```bash
# Check no firewall blocking port 5002
sudo ufw status
# Check process is running
ps aux | grep main.py
```

### No data updating in browser
```bash
# Verify demo data generator is running
curl -s http://localhost:5002/api/data | python3 -c "import sys,json; d=json.load(sys.stdin); print('RPM:', d.get('rpm'), 'Speed:', d.get('speed'))"
# Should show non-zero values
```

### Map tiles not loading (Weather screen)
```bash
# Leaflet.js needs internet for OpenStreetMap tiles
ping tile.openstreetmap.org
# If no internet, map shows empty but weather data still works
```

### `ModuleNotFoundError: No module named 'flask'`
```bash
source .venv/bin/activate
pip install -r requirements-x86.txt
```

---

## 11. Quick Test Checklist

- [ ] `./run_x86.sh` — starts without errors
- [ ] `http://localhost:5002` — dashboard loads in browser
- [ ] Init screen shows car sketch + progress bar + auto-transitions to A1
- [ ] A1 Main — gauges update with live data
- [ ] A2 Trip — chart renders, stats update
- [ ] A3 Weather — map loads, weather data shows
- [ ] A4 Service — diagnostics list renders
- [ ] Theme switch — all 3 themes render correctly
- [ ] Keyboard nav — LEFT/RIGHT cycles screens
- [ ] `curl /api/data` — returns JSON with live values
- [ ] `curl /api/config` — returns current theme/language
- [ ] Multiple browser tabs — all receive real-time updates
