#!/usr/bin/env bash
# Build a small demo repository with a realistic history: feature branches,
# merges, release tags, a hotfix, a branch that merges main back in, and
# local, remote-only and unpushed branches. The README screenshots are taken
# in it.
#
# Usage: scripts/demo-repo.sh DIR
# Creates DIR/weatherline (the working repository) and DIR/origin.git (its
# remote). Dates are relative to now, so the age column reads naturally.
set -euo pipefail

if (($# != 1)); then
  printf 'usage: %s DIR\n' "$0" >&2
  exit 2
fi
if [[ -e $1/weatherline || -e $1/origin.git ]]; then
  printf 'demo-repo.sh: %s already has a demo repository\n' "$1" >&2
  exit 1
fi
mkdir -p -- "$1"
root=$(cd -- "$1" && pwd -P)

# Keep the user's own git configuration (hooks, signing, merge drivers) out.
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
now=$(date +%s)

full_name() {
  case $1 in
    alice) echo "Alice Moreau" ;;
    ben) echo "Ben Okafor" ;;
    chen) echo "Chen Wei" ;;
    dana) echo "Dana Kowalski" ;;
  esac
}

at() { # who days-ago hours-ago
  local stamp="@$((now - $2 * 86400 - $3 * 3600)) +0000" name
  name=$(full_name "$1")
  export GIT_AUTHOR_NAME=$name GIT_COMMITTER_NAME=$name
  export GIT_AUTHOR_EMAIL=$1@example.com GIT_COMMITTER_EMAIL=$1@example.com
  export GIT_AUTHOR_DATE=$stamp GIT_COMMITTER_DATE=$stamp
}

commit() { # who days-ago hours-ago subject [body]
  at "$1" "$2" "$3"
  git add -A
  if (($# > 4)); then
    git commit -q -m "$4" -m "$5"
  else
    git commit -q -m "$4"
  fi
}

merge() { # who days-ago hours-ago branch [into]
  at "$1" "$2" "$3"
  local message="Merge branch '$4'"
  [[ -n ${5-} ]] && message+=" into $5"
  git merge -q --no-ff -m "$message" "$4"
}

replace() { # file old new: replace the one occurrence of old, which must exist
  python3 - "$@" <<'EOF'
import sys
from pathlib import Path
path, old, new = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text()
if text.count(old) != 1:
    sys.exit(f"demo-repo.sh: expected one {old!r} in {path}")
path.write_text(text.replace(old, new))
EOF
}

tag() { # who days-ago hours-ago name
  at "$1" "$2" "$3"
  git tag -a -m "weatherline ${4#v}" "$4"
}

git init -q --bare "$root/origin.git"
git init -q -b main "$root/weatherline"
cd "$root/weatherline"
git remote add origin "$root/origin.git"
mkdir -p weatherline tests

# --- first release ------------------------------------------------------------

cat > README.md <<'EOF'
# weatherline

A tiny weather forecast for your terminal.
EOF
cat > pyproject.toml <<'EOF'
[project]
name = "weatherline"
version = "0.1.0"
dependencies = ["requests"]

[project.scripts]
weatherline = "weatherline.cli:main"
EOF
echo '__version__ = "0.1.0"' > weatherline/__init__.py
commit alice 62 5 "Initial commit"

cat > weatherline/forecast.py <<'EOF'
"""Fetch forecasts from the Open-Meteo API."""
import requests

API = "https://api.open-meteo.com/v1/forecast"


def fetch(latitude, longitude):
    response = requests.get(API, params={
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
    }, timeout=10)
    response.raise_for_status()
    return response.json()["hourly"]
EOF
commit alice 61 3 "Fetch hourly forecasts from Open-Meteo"

cat > weatherline/cli.py <<'EOF'
import argparse

from . import forecast


def main():
    parser = argparse.ArgumentParser(prog="weatherline")
    parser.add_argument("latitude", type=float)
    parser.add_argument("longitude", type=float)
    args = parser.parse_args()
    hourly = forecast.fetch(args.latitude, args.longitude)
    for time, temp in zip(hourly["time"], hourly["temperature_2m"]):
        print(f"{time}  {temp:5.1f}°C")
EOF
commit alice 60 6 "Add a command line entry point"

git switch -q -c feature/units
cat > weatherline/units.py <<'EOF'
"""Unit conversion for temperatures and wind speeds."""


def fahrenheit(celsius):
    return celsius * 9 / 5 + 32


def mph(kmh):
    return kmh / 1.609344
EOF
commit ben 58 4 "Add imperial unit conversion"
cat > tests/test_units.py <<'EOF'
from weatherline import units


def test_freezing_point():
    assert units.fahrenheit(0) == 32


def test_boiling_point():
    assert units.fahrenheit(100) == 212


def test_mph():
    assert round(units.mph(100), 2) == 62.14
EOF
commit ben 57 2 "Test the unit conversions"

git switch -q main
cat > weatherline/cache.py <<'EOF'
"""Keep forecasts for ten minutes so repeated runs don't hit the API."""
import json
import time
from pathlib import Path

CACHE = Path.home() / ".cache" / "weatherline.json"
MAX_AGE = 600


def load(key):
    try:
        entry = json.loads(CACHE.read_text())[key]
    except (OSError, KeyError, ValueError):
        return None
    return entry["data"] if time.time() - entry["time"] < MAX_AGE else None


def store(key, data):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({key: {"time": time.time(), "data": data}}))
EOF
commit alice 56 1 "Cache forecasts for ten minutes" \
  "Every run fetched a fresh forecast, so a prompt or status bar that runs
weatherline on each refresh hit the API constantly. Forecasts only change
hourly, so ten minutes is plenty."
merge alice 55 3 feature/units
git branch -q -d feature/units
tag alice 55 2 v0.1.0

# --- charts, time zones and the second release --------------------------------

git switch -q -c feature/sparklines
cat > weatherline/render.py <<'EOF'
"""Draw a forecast as a sparkline."""
BARS = "▁▂▃▄▅▆▇█"


def sparkline(values):
    low, high = min(values), max(values)
    span = (high - low) or 1
    return "".join(BARS[int((v - low) / span * (len(BARS) - 1))] for v in values)
EOF
commit chen 52 6 "Draw temperatures as a sparkline"

git switch -q main
replace weatherline/forecast.py '    return response.json()["hourly"]' \
  $'    hourly = response.json().get("hourly")\n    if not hourly:\n        raise LookupError("no hourly forecast for this location")\n    return hourly'
commit dana 51 2 "Fix a crash when there is no hourly forecast" \
  "Locations far out at sea come back without an hourly block, and the
KeyError ended the program with a traceback. Raise a LookupError the
command line can report instead."

git switch -q feature/sparklines
cat > weatherline/render.py <<'EOF'
"""Draw a forecast as a sparkline."""
import shutil

BARS = "▁▂▃▄▅▆▇█"
COLOURS = [33, 39, 45, 51, 226, 214, 208, 196]


def sparkline(values, colour=True):
    width = shutil.get_terminal_size().columns
    values = values[:width]
    low, high = min(values), max(values)
    span = (high - low) or 1
    out = []
    for value in values:
        level = int((value - low) / span * (len(BARS) - 1))
        bar = BARS[level]
        out.append(f"\x1b[38;5;{COLOURS[level]}m{bar}\x1b[0m" if colour else bar)
    return "".join(out)
EOF
commit chen 50 5 "Colour the sparkline by temperature"
replace weatherline/render.py 'def sparkline(values, colour=True):' 'def sparkline(values, colour=True, width=None):'
replace weatherline/render.py '    width = shutil.get_terminal_size().columns' '    width = width or shutil.get_terminal_size().columns'
commit chen 49 3 "Fit the chart to the terminal width"
git switch -q main
merge alice 47 4 feature/sparklines
git branch -q -d feature/sparklines

git switch -q -c fix/timezones
replace weatherline/forecast.py '        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",' \
  $'        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",\n        "timezone": "auto",'
commit dana 45 6 "Show times in the location's own time zone"
git switch -q main
merge alice 44 2 fix/timezones
git branch -q -d fix/timezones
echo '__version__ = "0.2.0"' > weatherline/__init__.py
replace pyproject.toml 'version = "0.1.0"' 'version = "0.2.0"'
commit alice 43 5 "Release 0.2.0"
tag alice 43 4 v0.2.0

# --- alerts, a long-running branch that keeps up with main ---------------------

git switch -q -c feature/alerts
cat > weatherline/alerts.py <<'EOF'
"""Severe weather alerts from MeteoAlarm."""
import requests

FEED = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-{country}"


def fetch(country):
    response = requests.get(FEED.format(country=country), timeout=10)
    response.raise_for_status()
    return [w["info"][0]["headline"] for w in response.json().get("warnings", [])]
EOF
commit ben 40 4 "Fetch severe weather alerts"

git switch -q main
replace weatherline/cli.py '    parser.add_argument("longitude", type=float)' \
  $'    parser.add_argument("longitude", type=float)\n    parser.add_argument("--units", choices=["metric", "imperial"], default="metric")'
commit alice 38 3 "Choose metric or imperial units with --units"
cat > weatherline/config.py <<'EOF'
"""Read the default location from ~/.config/weatherline.toml."""
import tomllib
from pathlib import Path

PATH = Path.home() / ".config" / "weatherline.toml"


def default_location():
    try:
        data = tomllib.loads(PATH.read_text())
    except OSError:
        return None
    return data.get("latitude"), data.get("longitude")
EOF
commit chen 35 6 "Read the default location from a config file"

git switch -q feature/alerts
merge ben 33 2 main feature/alerts
cat >> weatherline/alerts.py <<'EOF'


def banner(headlines):
    return "\n".join(f"\x1b[1;31m⚠ {headline}\x1b[0m" for headline in headlines)
EOF
commit ben 31 5 "Show alerts above the forecast"

git switch -q main
cat >> README.md <<'EOF'

## Configuration

Put a default location in `~/.config/weatherline.toml`:

```toml
latitude = 59.33
longitude = 18.07
```
EOF
commit alice 29 3 "Document the config file"
git switch -q feature/alerts
merge ben 27 4 main feature/alerts
replace weatherline/alerts.py 'timeout=10)' 'timeout=5)'
commit ben 26 2 "Give up on the alert feed after five seconds"
git switch -q main
merge alice 24 6 feature/alerts
git branch -q -d feature/alerts

git switch -q -c docs/usage
cat >> README.md <<'EOF'

## Usage

```sh
weatherline 59.33 18.07 --units metric
```
EOF
commit dana 22 3 "Add a usage section to the README"
git switch -q main
merge alice 21 5 docs/usage
git branch -q -d docs/usage

cat > CHANGELOG.md <<'EOF'
# Changelog

## 0.3.0

- Severe weather alerts above the forecast.
- `--units` chooses metric or imperial units.
- A default location can be set in `~/.config/weatherline.toml`.
EOF
echo '__version__ = "0.3.0"' > weatherline/__init__.py
replace pyproject.toml 'version = "0.2.0"' 'version = "0.3.0"'
commit alice 19 4 "Release 0.3.0"
tag alice 19 3 v0.3.0

# --- a hotfix on the release branch ------------------------------------------

git switch -q -c release/0.3
cat >> weatherline/render.py <<'EOF'

ARROWS = "↓↙←↖↑↗→↘"


def wind_arrow(degrees):
    # Wind direction is where the wind comes from; the arrow shows where it goes.
    return ARROWS[round(degrees / 45) % 8]
EOF
cat > tests/test_render.py <<'EOF'
from weatherline.render import wind_arrow


def test_north_wind_blows_south():
    assert wind_arrow(0) == "↓"


def test_west_wind_blows_east():
    assert wind_arrow(270) == "→"
EOF
commit dana 16 5 "Point wind arrows the way the wind blows" \
  "The direction from the API is where the wind comes from, and the
arrows pointed there too, so every arrow was backwards."
echo '__version__ = "0.3.1"' > weatherline/__init__.py
replace pyproject.toml 'version = "0.3.0"' 'version = "0.3.1"'
commit dana 16 2 "Release 0.3.1"
tag dana 16 1 v0.3.1
git switch -q main
merge alice 15 4 release/0.3

# --- work in progress ----------------------------------------------------------

replace weatherline/forecast.py 'import requests' 'import importlib'
replace weatherline/forecast.py '    response = requests.get(API, params={' \
  $'    requests = importlib.import_module("requests")\n    response = requests.get(API, params={'
commit alice 9 6 "Import requests only when fetching" \
  "requests takes a third of the start-up time and a cached forecast never
needs it."

git switch -q -c feature/hourly-view
cat > weatherline/hourly.py <<'EOF'
"""A table of the next 24 hours."""


def table(hourly, hours=24):
    rows = zip(hourly["time"], hourly["temperature_2m"], hourly["wind_speed_10m"])
    return [f"{t[11:16]}  {temp:5.1f}°  {wind:4.1f} km/h" for t, temp, wind in list(rows)[:hours]]
EOF
commit chen 8 5 "Add an hourly table"
replace weatherline/hourly.py 'def table(hourly, hours=24):' 'def table(hourly, hours=24, wind=True):'
commit chen 6 3 "Make the wind column optional"
git switch -q main

git switch -q -c experiment/radar
cat > weatherline/radar.py <<'EOF'
"""Experimental: precipitation radar as braille dots."""
DOTS = "⠀⠁⠃⠇⡇⣇⣧⣷⣿"


def frame(grid):
    return "\n".join("".join(DOTS[min(cell, 8)] for cell in row) for row in grid)
EOF
commit ben 5 4 "Sketch a braille precipitation radar"
git switch -q main

replace weatherline/cli.py '    parser.add_argument("--units"' \
  $'    parser.add_argument("--days", type=int, default=1)\n    parser.add_argument("--units"'
commit alice 4 2 "Add a --days option"

# Publish what the team has pushed: main, the release branch and tags, the
# hourly view, and the radar experiment that only lives on the remote.
git push -q origin main release/0.3 feature/hourly-view experiment/radar --tags
git branch -q -D experiment/radar
git branch -q -u origin/main main
git branch -q -u origin/feature/hourly-view feature/hourly-view

# Local work that isn't pushed yet: one commit on main and a new branch.
replace weatherline/cli.py '    hourly = forecast.fetch(args.latitude, args.longitude)' \
  $'    try:\n        hourly = forecast.fetch(args.latitude, args.longitude)\n    except LookupError as error:\n        parser.exit(1, f"weatherline: {error}\\n")'
commit alice 0 5 "Report a missing forecast without a traceback"
git switch -q -c wip/icons
cat > weatherline/icons.py <<'EOF'
ICONS = {"clear": "☀", "cloudy": "☁", "rain": "☂", "snow": "❄", "storm": "⚡"}
EOF
commit dana 0 2 "Add weather icons"
git switch -q main

printf 'Demo repository ready in %s/weatherline\n' "$root"
