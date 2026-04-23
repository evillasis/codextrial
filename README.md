# Sun Exposure Calculator & 3M Film Recommendation

A command-line tool that calculates annual solar exposure for a building facade and recommends the appropriate 3M sun-protection film. Give it an address (or GPS coordinates) and a facade orientation, and it tells you exactly how many hours of direct sun hit your windows — weighted by intensity, filtered to your store's opening hours, and adjusted for altitude and nearby obstructions.

---

## Requirements

- Python 3.11 or later
- No third-party packages required — the tool uses only the Python standard library

---

## Quick start

```bash
# Clone the repository
git clone https://github.com/evillasis/codextrial.git
cd codextrial

# Run a basic analysis (south-facing facade in Madrid)
python main.py --lat 40.4168 --lon -3.7038 --facade-azimuth 180 --address "Gran Via 1, Madrid"
```

Sample output:

```
========================================================
 SUN EXPOSURE & 3M FILM RECOMMENDATION
========================================================
 Address  : Gran Via 1, Madrid
 Location : 40.41680°, -3.70380°

 --- Exposure Analysis ---
Facade direction : S (180.0°)
Annual direct sun: 3633 h/year
Peak month       : Mar (12.0 h/day avg)
Peak single day  : 12.0 h
Energy score     : 1270  (intensity-weighted hours)

 --- Recommendation ---
 Risk level  : HIGH
 Protect?    : YES — film recommended
 Film type   : 3M Prestige Series (medium)
 Reason      : Facade faces S (180°). Peak exposure is 12.0 h/day in March
               with 3633 annual direct-sun hours.
========================================================
```

---

## How to specify the location

### Option A — explicit coordinates

```bash
python main.py --lat 40.4168 --lon -3.7038 --facade-azimuth 180
```

Latitude and longitude in decimal degrees. West longitudes and south latitudes are negative.

### Option B — address (requires internet)

Omit `--lat` / `--lon` and provide `--address`. The tool geocodes it automatically via Nominatim (OpenStreetMap):

```bash
python main.py --address "Oxford Street 1, London" --facade-azimuth 180
```

---

## How to specify the facade orientation

You must tell the tool which direction your windows face. Three ways to do this:

### 1. Facade azimuth — exact degrees

The outward-facing compass bearing of the window wall. 0 = North, 90 = East, 180 = South, 270 = West.

```bash
--facade-azimuth 225          # SW-facing wall
```

### 2. Street angle — analyse both sides at once

Give the compass bearing of the street itself. The tool creates two buildings: one for each side of the street.

```bash
--street-angle 45             # NE–SW street → SE facade and NW facade
--street-side right           # only analyse the right-hand side (optional)
```

### 3. Cardinal direction — human-friendly shorthand

```bash
--cardinal SW                 # accepts N, NNE, NE, ENE, E, ESE, SE, SSE,
                              #         S, SSW, SW, WSW, W, WNW, NW, NNW
```

### 4. Auto-derive from OSM (requires internet)

Let the tool find the nearest road and calculate the street angle automatically:

```bash
--auto-street
```

---

## Auto-derive all inputs with `--auto`

When you have an internet connection, a single `--auto` flag replaces manual lookups for coordinates, street angle, altitude, and nearby building shadows:

```bash
python main.py --address "Passeig de Gràcia 43, Barcelona" --auto
```

This runs four lookups in sequence:

| Lookup | Source | What it sets |
|---|---|---|
| Coordinates | Nominatim (OSM) | lat / lon from address |
| Street angle | Overpass (OSM) | nearest road bearing |
| Altitude | Open-Elevation / Open-Topo-Data | metres above sea level |
| Building shadows | Overpass (OSM) | blocking elevation angles from nearby buildings |

You can enable individual lookups instead of all four:

```bash
--auto-street        # only street angle
--auto-elevation     # only altitude
--auto-buildings     # only nearby building shadows
```

---

## Retail store analysis

For commercial spaces, several additional flags refine the calculation to match real customer patterns.

### Operating hours

Only count sun exposure while the store is open. Hours are in local solar time.

```bash
--operating-hours 11,21       # 11 AM to 9 PM
```

### Peak sales weighting

Flag the hours with the highest customer traffic. Sun exposure during these periods counts more in the final score because that is when customer comfort matters most.

```bash
--peak-weights                # default: 1–3 PM × 1.5, 6–8 PM × 1.3
```

Custom peak windows (repeatable, implies `--peak-weights`):

```bash
--peak-window 12,14,2.0       # noon–2 PM counts double
--peak-window 17,19,1.5       # 5–7 PM counts 1.5×
```

### Entry and checkout queue zones

Analyse specific areas of the store as separate zones. Each zone gets its own report block.

```bash
--entry-azimuth 90            # direction the entry facade faces
--queue-azimuth 270           # direction customers face at checkout
```

### Manual obstructions

A mountain range or neighbouring building that shades the site during certain hours:

```bash
--obstruction AZ_START,AZ_END,BLOCKING_ELEVATION
--obstruction 250,300,20      # hill to the WSW blocks sun below 20°
--obstruction 60,90,35        # tall building to the ENE blocks sun below 35°
```

`--obstruction` can be repeated for multiple obstructions. When combined with `--auto-buildings`, both sources are merged.

### Altitude

Higher altitude means thinner atmosphere and stronger UV (+4% per 300 m). The tool adjusts the score and recommendation accordingly.

```bash
--altitude 2600               # metres above sea level
```

Or derive it automatically:

```bash
--auto-elevation
```

---

## Full retail example

A store in Bogotá (2 600 m altitude), open 11 AM to 9 PM, with peak traffic at lunch and early evening, a mountain to the west, analysed across the main facade, entry door, and checkout queue:

```bash
python main.py \
  --address "Calle 72, Bogotá" \
  --auto \
  --operating-hours 11,21 \
  --peak-weights \
  --entry-azimuth 90 \
  --queue-azimuth 270 \
  --day-step 7
```

The tool prints three separate report blocks — one per zone — so you can specify different film products for each wall.

---

## Understanding the output

### Risk levels and film recommendations

| Level | Daily score | Film recommendation | When to use |
|---|---|---|---|
| NONE | < 0.5 | No film needed | North-facing or heavily shaded |
| LOW | 0.5 – 1.2 | Decorative tint only | Indirect or brief direct exposure |
| MODERATE | 1.2 – 2.2 | 3M Prestige Series (light) | Partial exposure, mild climate |
| HIGH | 2.2 – 3.5 | 3M Prestige Series (medium) | Strong direct exposure, warm climate |
| CRITICAL | ≥ 3.5 | 3M Prestige Series (dark) or Ceramic IR | High-altitude or tropical south/west facades |

### The energy score

The **energy score** is more meaningful than raw hours. It weights each hour of direct sun by two factors:

- **cos(angle to facade)** — sun hitting at a glancing angle contributes less than sun hitting straight on
- **sin(elevation)** — low-angle sun (morning/evening) passes through more atmosphere and is weaker than overhead sun

A south-facing facade in Madrid and a south-facing facade in Oslo might receive similar *hours* of sun, but the Madrid score will be higher because the sun reaches a greater elevation.

### Why south-facing facades peak in March, not June

At mid-latitudes, the sun rises in the north-east and sets in the north-west during summer, spending several hours in the northern sky where it cannot reach a south-facing wall. At the spring and autumn equinoxes the sun rises due east and sets due west, illuminating the south facade for the entire 12-hour day. This means a south-facing facade often has its worst month in March or September, not June.

---

## Speed vs. accuracy

The simulation samples sun position once per hour. Two parameters control the trade-off between speed and accuracy:

| Flag | Default | Effect |
|---|---|---|
| `--day-step N` | 7 | Sample every N-th day; 1 = every day (most accurate), 14 = fast |
| `--year YEAR` | 2025 | Calendar year to simulate |

For a quick estimate use `--day-step 14`. For a final client report use `--day-step 1`.

---

## Using the library in your own code

The tool is structured as a Python package. You can import it directly:

```python
from sun_exposure import Building, ExposureCalculator, recommend_protection
from sun_exposure.building import StoreProfile, ObstructionProfile
from sun_exposure.recommendation import format_report
from sun_exposure.geo import geocode, get_street_angle, get_elevation, get_building_obstructions

# Resolve location automatically
coords = geocode("Passeig de Gràcia 43, Barcelona")
lat, lon = coords["lat"], coords["lon"]

# Auto-derive street angle
street_bearing = get_street_angle(lat, lon)

# Build facades for both sides of the street
from sun_exposure import facade_from_street_angle
buildings = facade_from_street_angle(lat, lon, street_bearing)

# Define a retail store profile
altitude_m = get_elevation(lat, lon)
nearby = get_building_obstructions(lat, lon)

profile = StoreProfile(
    altitude_m=altitude_m,
    operating_hours=(11.0, 21.0),
    apply_peak_weights=True,
    obstructions=nearby,
)

# Calculate and print
calc = ExposureCalculator(year=2025, day_step=7)
for building in buildings:
    result = calc.calculate(building, profile)
    rec = recommend_protection(result)
    print(format_report(result, rec))
```

### Key classes

| Class | Where | Purpose |
|---|---|---|
| `SolarPosition(lat, lon)` | `sun_exposure.solar_position` | `.position(datetime)` → azimuth, elevation, is_daylight |
| `Building(lat, lon, facade_azimuth)` | `sun_exposure.building` | One facade; `.angle_to_sun(az)` |
| `StoreProfile(...)` | `sun_exposure.building` | Operating hours, peak weights, altitude, obstructions |
| `ObstructionProfile(list)` | `sun_exposure.building` | Horizon obstruction sectors; `.is_blocked(az, el)` |
| `ExposureCalculator(year, hour_step, day_step)` | `sun_exposure.exposure` | `.calculate(building, store_profile)` → `ExposureResult` |
| `ExposureResult` | `sun_exposure.exposure` | annual\_hours, weighted\_score, altitude\_factor, … |
| `Recommendation` | `sun_exposure.recommendation` | level, protect, film\_type, reason, score |

---

## Running the tests

```bash
python -m pytest tests/ -v
```

All 56 tests run without a network connection (HTTP calls are mocked).

---

## Architecture overview

```
sun_exposure/
  solar_position.py     NOAA solar algorithm — azimuth & elevation for any lat/lon/datetime
  building.py           Building, StoreProfile, ObstructionProfile
  exposure.py           ExposureCalculator — hourly sampling across all 365 days
  recommendation.py     Threshold logic and formatted report
  geo/
    geocode.py          Nominatim: address → lat/lon
    elevation.py        Open-Elevation + Open-Topo-Data: lat/lon → altitude
    street_angle.py     Overpass: nearest road → compass bearing
    nearby_buildings.py Overpass: building footprints → ObstructionProfile
main.py                 CLI entry point
tests/
  test_solar_position.py   14 tests — solar math, building geometry, exposure, recommendations
  test_enhancements.py     22 tests — retail store features
  test_geo.py              20 tests — geo lookups (all HTTP mocked)
```
