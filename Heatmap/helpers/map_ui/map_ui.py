import folium
import json


# Color gradient legend
def add_shared_risk_legend(m):
    """
    Add a fixed color-gradient legend to the Folium map.
    The legend explains the yellow-to-red alarm intensity scale used by the heatmap layers.
    """

    legend_html = """
    <div style="
        position: fixed;
        top: 20px; left: 50px; z-index: 1000;
        font-size: 12px;
        font-family: Arial, Helvetica, sans-serif;
        color: #333;
        background: rgba(255, 255, 255, 0.6); 
        backdrop-filter: blur(6px);
        padding: 10px 14px;
        border-radius: 8px;
        width: 260px;
    ">
        <div style="margin-bottom: 6px;">
            <b>Alarm Intensity</b>
        </div>

        <div style="
            height: 10px;
            background: linear-gradient(to right, #FFF176, #FFD600, #FF6D00, #D50000);
            border-radius: 4px;
            margin-bottom: 6px;
        "></div>

        <div style="display: flex; justify-content: space-between; font-size: 11px; color: #666;">
            <span>Low</span>
            <span>High</span>
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))


# Dynamic info box shell
def add_dynamic_info_box(m):
    """
    Add an empty fixed-position summary box to the map.
    The content is filled dynamically by JavaScript in add_toggle_script() based on the selected timeframe.
    """

    info_box_html = """
    <div id="dynamic-info-box" style="
        position: fixed; bottom: 40px; left: 50px; z-index: 1000;
        background: rgba(0,0,0,0.82); color: white;
        padding: 14px 18px; border-radius: 6px;
        font-size: 13px; font-family: Arial, Helvetica, sans-serif;
        border-left: 3px solid #fd8d3c; max-width: 280px;
    ">
        <b>Dataset Summary</b><br>
        <span id="info-content" style="color:#aaa; font-size:12px;">
            Loading...
        </span>
    </div>
    """
    m.get_root().html.add_child(folium.Element(info_box_html))


def add_selector_ui(m):
    """
    Add the custom filter panel to the map.
    The panel lets the user switch between:
    - alarm metrics
    - gas subtypes
    - time ranges
    - visited-location overlay visibility
    The actual layer-switching behavior is handled by add_toggle_script().
    """

    selector_html = """
    <div id="custom-filter-panel" style="
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 9999;
        background: rgba(255,255,255,0.88);
        backdrop-filter: blur(6px);
        padding: 14px 16px;
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.18);
        font-family: Arial, Helvetica, sans-serif;
        font-size: 13px;
        color: #333;
        min-width: 240px;
    ">
        <div style="margin-bottom: 10px;">
            <b>Metric</b>
        </div>

        <label style="display:block; margin-bottom:4px;">
            <input type="radio" name="metric" value="sessions" checked>
            Sessions with Alarms
        </label>
        <label style="display:block; margin-bottom:4px;">
            <input type="radio" name="metric" value="gas">
            Gas Alarms
        </label>
        <label style="display:block; margin-bottom:4px;">
            <input type="radio" name="metric" value="emg">
            Emergency Alarms
        </label>
        <label style="display:block; margin-bottom:10px;">
            <input type="radio" name="metric" value="repeat">
            Multi-Day Alarm Presence
        </label>

        <div id="gas-type-panel" style="margin-bottom: 10px; margin-top: 8px; display:none;">
            <b>Gas Type</b>
            <label style="display:block; margin-top:6px; margin-bottom:4px;">
                <input type="radio" name="gas_type" value="all" checked>
                All Gas Types
            </label>
            <label style="display:block; margin-bottom:4px;">
                <input type="radio" name="gas_type" value="co">
                Carbon Monoxide
            </label>
            <label style="display:block; margin-bottom:4px;">
                <input type="radio" name="gas_type" value="h2s">
                Hydrogen Sulfide
            </label>
            <label style="display:block; margin-bottom:4px;">
                <input type="radio" name="gas_type" value="o2">
                Oxygen
            </label>
            <label style="display:block; margin-bottom:10px;">
                <input type="radio" name="gas_type" value="comb">
                Combustible
            </label>
        </div>

        <div style="margin-bottom: 10px; margin-top: 8px;">
            <b>Time Range</b>
        </div>

        <label style="display:block; margin-bottom:4px;">
            <input type="radio" name="timeframe" value="2w" checked>
            Last 2 Weeks
        </label>
        <label style="display:block; margin-bottom:4px;">
            <input type="radio" name="timeframe" value="1m">
            Last Month
        </label>
        <label style="display:block; margin-bottom:10px;">
            <input type="radio" name="timeframe" value="all">
            All Data
        </label>

        <div style="margin-bottom: 8px; margin-top: 8px;">
            <b>Overlays</b>
        </div>

        <label style="display:block; margin-bottom:4px;">
            <input type="checkbox" id="toggle-visited" checked> 
            Show Visited
        </label>
    </div>
    """
    m.get_root().html.add_child(folium.Element(selector_html))


def add_toggle_script(m, bundle_registry):
    """
    Add JavaScript logic for interactive layer switching.

    This function connects the custom HTML controls to the Folium layers.

    It controls:
    - selected metric layer
    - selected gas subtype layer
    - selected timeframe
    - visited-location overlay toggle
    - dynamic summary box content

    Parameters
    ----------
    m : folium.Map
        Folium map object.

    bundle_registry : dict
        Dictionary returned from build_timeframe_bundle() for each timeframe.
        Expected structure:

        {
            "2w": {
                "metrics": {...},
                "hex": <folium layer>,
                "visited_hex": <folium layer>,
                "summary": {...}
            },
            ...
        }
    """

    map_name = m.get_name()

    # These lists/dicts map Python Folium layer objects to JavaScript variables.
    # The generated JS uses these maps to add/remove layers interactively.
    metric_map_entries = []
    hex_map_entries = []
    visited_map_entries = {}
    summary_dict = {}

    for timeframe_key, bundle in bundle_registry.items():
        # Register heatmap layers, e.g. "2w__sessions", "1m__gas_co"
        for metric_key, layer in bundle.get("metrics", {}).items():
            metric_map_entries.append(
                f'"{timeframe_key}__{metric_key}": {layer.get_name()}'
            )

        # Register transparent alarm hexagon overlay for this timeframe.
        if bundle.get("hex") is not None:
            hex_map_entries.append(
                f'"{timeframe_key}": {bundle["hex"].get_name()}'
            )

        # Register gray visited-only hexagon overlay for this timeframe.
        if bundle.get("visited_hex") is not None:
            visited_map_entries[timeframe_key] = bundle["visited_hex"].get_name()

        # Register summary data used by the bottom-left info box.
        summary_dict[timeframe_key] = bundle.get("summary", {})

    js_metric_map = ",\n".join(metric_map_entries)
    js_hex_map = ",\n".join(hex_map_entries)
    js_visited_map = ",\n".join(
        f'"{k}": {v}' for k, v in visited_map_entries.items()
    )
    js_summary = json.dumps(summary_dict)

    script = f"""
    <script>
    document.addEventListener("DOMContentLoaded", function() {{
        var map = {map_name};

        var metricMap = {{
            {js_metric_map}
        }};

        var hexMap = {{
            {js_hex_map}
        }};

        var visitedMap = {{
            {js_visited_map}
        }};

        var summaryData = {js_summary};

        function getCheckedValue(name) {{
            var el = document.querySelector(`input[name="${{name}}"]:checked`);
            return el ? el.value : null;
        }}

        function removeAll(obj) {{
            Object.values(obj).forEach(function(layer) {{
                if (layer && map.hasLayer(layer)) {{
                    map.removeLayer(layer);
                }}
            }});
        }}

        function updateGasPanelVisibility() {{
            var metric = getCheckedValue("metric");
            var gasPanel = document.getElementById("gas-type-panel");
            if (!gasPanel) return;
            gasPanel.style.display = (metric === "gas") ? "block" : "none";
        }}

        function updateInfoBox(timeframe) {{
            var info = summaryData[timeframe];
            var box = document.getElementById("info-content");
            if (!box || !info) return;

            box.innerHTML = `
                View: <b>${{info.label}}</b><br>
                H3 resolution: <b>${{info.h3_res}}</b><br>
                Alarm H3 cells: <b>${{(info.alarm_cells || 0).toLocaleString()}}</b><br>
                Visited-only H3 cells: <b>${{(info.visited_only_cells || 0).toLocaleString()}}</b><br>
                <hr style="border-color:#444; margin:6px 0">
                Total sessions: <b>${{(info.total_sessions || 0).toLocaleString()}}</b><br>
                Alarm Sessions: <b>${{(info.sessions_w_alarms || 0).toLocaleString()}}</b><br>
                Mapped alarm sessions: <b>${{(info.mapped_alarm_sessions || 0).toLocaleString()}}</b><br>
                <hr style="border-color:#444; margin:6px 0">
                <span style="color:#aaa; font-size:11px;">Location Quality</span><br>
                Location Score 4: <b>${{info.loc_score_4 || 0}}</b> sessions<br>
                Location Score 3: <b>${{info.loc_score_3 || 0}}</b> sessions<br>
                Location Score 2: <b>${{info.loc_score_2 || 0}}</b> sessions<br>
                Location Score 1: <b>${{info.loc_score_1 || 0}}</b> sessions<br>
                Location Score 0: <b>${{info.loc_score_0 || 0}}</b> sessions<br>
            `;
        }}

        function updateLayers() {{
            var metric = getCheckedValue("metric");
            var timeframe = getCheckedValue("timeframe");
            var gasType = getCheckedValue("gas_type") || "all";

            if (!metric || !timeframe) return;

            var metricKey = (metric === "gas")
                ? `${{timeframe}}__gas_${{gasType}}`
                : `${{timeframe}}__${{metric}}`;

            removeAll(metricMap);
            removeAll(hexMap);
            removeAll(visitedMap);

            var visitedToggle = document.getElementById("toggle-visited");
            if (visitedToggle && visitedToggle.checked && visitedMap[timeframe]) {{
                map.addLayer(visitedMap[timeframe]);
            }}

            if (metricMap[metricKey]) {{
                map.addLayer(metricMap[metricKey]);
            }}

            if (hexMap[timeframe]) {{
                map.addLayer(hexMap[timeframe]);
            }}

            updateGasPanelVisibility();
            updateInfoBox(timeframe);
        }}

        document.querySelectorAll('input[name="metric"]').forEach(function(el) {{
            el.addEventListener("change", updateLayers);
        }});

        document.querySelectorAll('input[name="timeframe"]').forEach(function(el) {{
            el.addEventListener("change", updateLayers);
        }});

        document.querySelectorAll('input[name="gas_type"]').forEach(function(el) {{
            el.addEventListener("change", updateLayers);
        }});

        var visitedToggle = document.getElementById("toggle-visited");
        if (visitedToggle) {{
            visitedToggle.addEventListener("change", updateLayers);
        }}

        updateGasPanelVisibility();
        updateLayers();
    }});
    </script>
    """
    m.get_root().html.add_child(folium.Element(script))
