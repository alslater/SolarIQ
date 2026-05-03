# SolarIQ

A self-hosted dashboard for homes with a SolaX inverter, battery storage, and an Octopus Agile tariff. SolarIQ shows live energy flows, tracks daily costs, displays historical usage, and calculates an optimised battery charging schedule for the following day.

## Features

- **Today** — live battery SOC, solar generation, grid import/export, cost, and Agile rate cards, updated every 5 minutes. Charts show per-slot energy flows, actual vs Solcast solar forecast, and today's import/export rates.
- **Inverter** — real-time inverter stats (power flows, battery, temperatures, grid voltage) with configurable auto-refresh (5 s – 5 min).
- **Charging Strategy** — tomorrow's optimised Time-of-Use schedule derived from Agile prices, Solcast solar forecast, and a temperature-adjusted load profile. See [`docs/strategy.md`](docs/strategy.md) for how the algorithm works.
- **History** — hourly or daily aggregated energy and cost data for any date range.
- **Settings** — export calibration and cache management.

## Requirements

- Python 3.11
- Node.js 20 (used by Reflex to build the frontend)
- [CBC solver](https://github.com/coin-or/Cbc) (`coinor-cbc` on Debian/Ubuntu)
- InfluxDB 1.8 with inverter data (written by a SolaX logger)
- Octopus Agile import and export tariffs
- Solcast account with a rooftop site configured

## Development

### 1. Install dependencies

```bash
pip install pipenv
pipenv sync --dev
```

### 2. Configure

```bash
cp solariq.ini.example solariq.ini
# Edit solariq.ini — fill in InfluxDB host, Octopus API key, Solcast key, etc.
```

### 3. Run

In one terminal start the Reflex web app:

```bash
pipenv run reflex run
```

In a second terminal start the background worker (fetches live data every 5 minutes and runs the daily strategy calculation):

```bash
pipenv run python -m solariq.worker
```

The UI is available at `http://localhost:3002`. The first start compiles the Next.js frontend — this takes 30–60 seconds; subsequent starts are fast.

### 4. Tests

```bash
pipenv run pytest
```

## Docker deployment

The application is split into two containers defined in `docker-compose.yaml`:

| Container | Role |
|-----------|------|
| `worker` | Fetches live data, runs the optimiser, writes shared cache files |
| `web` | Serves the Reflex UI; reads from the cache written by the worker |

### Configuration

```bash
mkdir -p config cache logs
cp solariq.ini.example config/solariq.ini
# Edit config/solariq.ini with real credentials
```

Set `API_URL` in `docker-compose.yaml` to the IP or hostname of the machine running the containers so that browser clients can reach the backend websocket (e.g. `http://192.168.1.50:8002`). Also replace `YOUR_DOCKERHUB_USERNAME` with your Docker Hub username, or use a local image name.

### x86 (standard PC / server)

Build and run locally:

```bash
docker build -t solariq:latest .
# Update the image name in docker-compose.yaml to match, then:
docker compose up -d
```

Or build and push to Docker Hub for deployment elsewhere:

```bash
docker build -t YOUR_DOCKERHUB_USERNAME/solariq:latest .
docker push YOUR_DOCKERHUB_USERNAME/solariq:latest
docker compose up -d
```

### Raspberry Pi (ARM64)

The Pi runs an ARM64 OS. If you are **building on the Pi itself**:

```bash
docker build -t YOUR_DOCKERHUB_USERNAME/solariq:latest .
docker push YOUR_DOCKERHUB_USERNAME/solariq:latest   # optional
docker compose up -d
```

If you are **cross-compiling on an x86 machine** and deploying to the Pi, use `docker buildx`:

```bash
# One-time setup — create a multi-arch builder
docker buildx create --name multiarch --use

# Build for ARM64 and push to Docker Hub
docker buildx build \
  --platform linux/arm64 \
  -t YOUR_DOCKERHUB_USERNAME/solariq:latest \
  --push .
```

Then on the Pi:

```bash
mkdir -p config cache logs
cp solariq.ini.example config/solariq.ini
# Edit config/solariq.ini
# Edit docker-compose.yaml — set API_URL and YOUR_DOCKERHUB_USERNAME
docker compose up -d
```

### Persistent volumes

| Host path | Container path | Purpose |
|-----------|---------------|---------|
| `./config/solariq.ini` | `/app/solariq.ini` | Configuration (mounted read-only) |
| `./cache/` | `/app/cache/` | Cached strategy, rates, and solar forecast JSON |
| `./logs/` | `/app/logs/` | Log output (enable `log_file` in `solariq.ini`) |

### Scaling the web tier

The worker must run as a single instance. The web container is stateless and can be scaled:

```bash
docker compose up --scale web=2 -d
```

### First-start note

On the first run Reflex compiles the Next.js frontend inside the container. This takes approximately 60–90 seconds on a Pi 4; on x86 hardware it is much faster. Subsequent restarts reuse the compiled output and start in a few seconds. Pulling a new image triggers a full recompile.
