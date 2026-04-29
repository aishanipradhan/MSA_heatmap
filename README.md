# MSA Safety – Grid Heatmap

Data preprocessing and heatmap pipeline for IoT event data. Transforms raw event-level data from MSA Safety devices into interactive customer-level heatmaps that visualize alarm activity, location coverage, and session-level location quality scores.

## Overview

This project takes raw events data, computes session-level location scores, and renders the aggregated results as an interactive HTML heatmap built on Folium and H3 hexagonal grids. Each output map includes:

- Alarm intensity heatmaps across multiple metrics (sessions, gas alarms, emergency alarms, multi-day alarm presence)
- Gas-subtype breakdowns (CO, H₂S, O₂, combustible)
- Visited-location coverage layer
- Time-window selection (Last 2 Weeks, Last Month, All Data)
- Per-cell hover tooltips with detailed counts
- Dynamic dataset summary box and color gradient legend

## Project Structure

```
Heatmap/
├── implement.ipynb              # Main entry point – generates the heatmap
├── data/                        # Place input event data here (empty in repo for privacy)
└── helpers/
    ├── validation_helpers/
    │   ├── filtering_helper.py
    │   ├── session_length_helper.py
    │   └── location_score_function.py
    ├── heatmap_building/
    │   ├── aggregation.py
    │   ├── location_matching.py
    │   └── heatmap_builder.py
    ├── map_ui/
    │   ├── map_layers.py
    │   └── map_ui.py
    └── Protobuffer_Deserialization/
        └── decoding.py
```

## Setup

### Dependencies

- Pandas
- Folium
- H3
- Numpy
- Protobuf (for decoding raw event data, optional if MSA uses their own deserialization)

Install with:

```bash
pip install pandas folium h3 numpy protobuf
```

### Data

Place the raw events dataset in the `Heatmap/data/` directory. The directory is intentionally empty in the repository for privacy reasons. The pipeline expects event-level data with the following key columns:

- `SESSION_ID`, `CUSTOMER_ID`, `EVENT_ID`
- `LOGGED_AT` (timestamp)
- `EVENT_TYPE` (e.g., `LOCATION`, `ALARM`, `MODE`)
- `META_ALARM`, `META_GAS`, `META_MODE`, `META_TYPE`
- `META_ENCODED_PROTO` (Protocol Buffer-encoded payload)

## Pipeline

The pipeline runs end-to-end from `implement.ipynb` and proceeds through nine stages:

### 1. Filter for Correct Mode Sequences
`filtering_helper.py → filter_correct_modes`

For each session, identifies a valid operating window starting at the first `NORMAL` mode and ending at the first subsequent `CHARGING` or `OFF` mode. Sessions without both a valid start and end are discarded.

### 2. Create Mapped Events DataFrame
`Protobuffer_Deserialization/decoding.py → deserialize_events`

Deserializes Protocol Buffer-encoded event data, extracts and scales latitude/longitude for `LOCATION` events, and flags valid GPS readings (filtering out the sentinel value `214.748365`).

### 3. Filter Target Alarm Sessions
`filtering_helper.py → filter_target_alarm_sessions`

Keeps only sessions containing at least one target alarm (gas or worker emergency). Non-target alarm rows are removed; non-alarm events are retained.

**Included alarms:**
- **Gas:** `ALARM_GAS_EXPOSURE`, `ALARM_GAS_DEFICIENCY`, `ALARM_GAS_STEL`, `ALARM_GAS_TWA`, `ALARM_GAS_OVERRANGE`, `ALARM_GAS_UNDERRANGE`
- **Worker emergency:** `ALARM_WORKER_EMERGENCY`, `ALARM_NOMOTION`, `ALARM_NOMOTION_NORESPONSE`, `ALARM_REMOTE_EVACUATION`, `ALARM_CHECKIN_NORESPONSE`

### 4. Calculate Location Scores
`session_length_helper.py` and `location_score_function.py → location_validation`

Computes a 0–4 session-level location quality score using four metrics:

- `pct_valid_gps` – fraction of valid GPS points
- `density` – valid location points per active hour vs. baseline
- `large_gap_fraction` – fraction of alarms far from any location ping
- `concentration_window` – temporal clustering score

Scored output is merged back onto the full events DataFrame.

### 5. Match Alarms to Locations
`location_matching.py → assign_locations_to_alarms`

For each alarm, finds the nearest location ping within the same session (checking both directions in time) and attaches matched coordinates plus the time delta.

### 6. Build H3 Aggregations
`aggregation.py → build_alarm_h3_agg`, `build_visited_h3_agg`

Converts alarm and location coordinates into H3 hexagonal cells (default resolution 9, industrial/factory-level granularity) and aggregates per-cell metrics (session counts, alarm days, gas/emergency counts, gas-type breakdowns). Normalizes counts via log-transform for heatmap intensity weights.

### 7. Build Map Layers
`map_layers.py → build_timeframe_bundle`

Constructs all visual layers for each timeframe:

- Gray hexagons for visited locations
- Yellow-to-red heatmaps for each metric and gas subtype
- Transparent alarm hexagon overlay with hover tooltips
- Summary dictionary used by the info box

### 8. Build Interactive UI
`map_ui.py`

Adds the legend, dynamic dataset summary box, filter panel (metric / gas type / time range / overlay toggle), and JavaScript layer-switching logic to the map.

### 9. Generate the Heatmap
`heatmap_builder.py → generate_customer_heatmap`

Top-level orchestration function. Filters to one customer, defines the three time windows anchored on the latest activity, builds aggregations and layers for each, attaches the UI, and saves the final interactive HTML.

## Usage

From `implement.ipynb`:

```python
from helpers.heatmap_building.heatmap_builder import generate_customer_heatmap

m = generate_customer_heatmap(
    data=events_df,
    customer_id="CUSTOMER_ID_HERE",
    output_file="output/customer_heatmap.html",
    h3_res=9
)
```

The H3 resolution is configurable. Resolution 9 (~0.1 km² hexagons) targets industrial/factory-level granularity; lower values give coarser regional views, higher values give finer detail.

## Assumptions

- Only sessions with a valid mode sequence (`NORMAL → OFF` or `NORMAL → CHARGING`) have reliable device activity.
- GPS readings outside the normal coordinate range are sentinel values; specifically, `214.748365` indicates an invalid reading.
- The gray boundary layer includes location records from all sessions with a valid mode sequence and valid location data.
- Alarm mapping is restricted to sessions containing worker emergency or gas alarms (see Step 3).
- Heatmap granularity defaults to industrial/factory level (H3 resolution 9), configurable in code.

## Output

Each run produces a self-contained interactive HTML file. Open it in any modern browser to explore the heatmap — no server required. The map includes:

- Base tiles via CartoDB (free, no API key)
- All layers, controls, and tooltips embedded in the single file

## Authors

- **Aishani Pradhan**
- **Elizabeth Szeto**
- **Erica Wang**

## References

- Technical Specification: `TS_MSA_Heatmap` (v1.0, April 2026)
- [H3 documentation](https://h3geo.org/)
- [Folium documentation](https://python-visualization.github.io/folium/)
