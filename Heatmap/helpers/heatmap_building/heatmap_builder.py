import pandas as pd
import folium

from helpers.heatmap_building.aggregation import *
from helpers.map_ui.map_layers import build_timeframe_bundle

from helpers.map_ui.map_ui import (
    add_shared_risk_legend,
    add_dynamic_info_box,
    add_selector_ui,
    add_toggle_script
)


def generate_customer_heatmap(data, customer_id, output_file, h3_res=9):
    """
    Generate and save an interactive alarm heatmap for one customer.

    This function is the main pipeline wrapper. It:
    1. Filters data to one customer.
    2. Separates valid GPS location rows.
    3. Keeps sessions with usable alarm-location mapping scores.
    4. Builds alarm and visited-location H3 aggregations for each timeframe.
    5. Adds heatmap, hexagon, legend, filter panel, and summary UI layers.
    6. Saves the final Folium map as an HTML file.

    Parameters
    ----------
    data : pd.DataFrame
        Full event-level dataset.

    customer_id : str
        Customer ID used to filter the data.

    output_file : str
        Path where the generated HTML map will be saved.

    h3_res : int
        H3 resolution used for hexagon aggregation.

    Returns
    -------
    folium.Map
        Interactive Folium map object.
    """

    # 1. Filter to one customer
    customer = data[data["CUSTOMER_ID"] == customer_id].copy()

    # Valid GPS points are used for the gray visited-location layer.
    valid_gps = (
        (customer["gps_valid"] == True) |
        (customer["gps_valid"].astype(str).str.lower() == "true")
    )

    customer_location = customer[
        (customer["EVENT_TYPE"] == "LOCATION") &
        valid_gps &
        (customer["latitude"].between(-90, 90)) &
        (customer["longitude"].between(-180, 180)) &
        (customer["latitude"] != 214.748365) &
        (customer["longitude"] != 214.748365)
    ].copy()

    # Location-score rows describe whether alarm sessions have usable location coverage.
    loc_score = customer[customer["location_score"].notnull()].copy()

    # Only score 2–4 sessions are used for alarm visualization.
    vis_sessions = set(
        loc_score.loc[
            loc_score["location_score"].between(2, 4),
            "SESSION_ID"
        ]
    )

    vis_df = customer[customer["SESSION_ID"].isin(vis_sessions)].copy()

    # 2. Define timeframes
    anchor_time = pd.to_datetime(vis_df["LOGGED_AT"]).max()
    start_2w = anchor_time - pd.Timedelta(days=14)
    start_1m = anchor_time - pd.Timedelta(days=30)

    timeframes = {
        "2w": ("Last 2 Weeks", start_2w, anchor_time),
        "1m": ("Last Month", start_1m, anchor_time),
        "all": ("All Data", None, None),
    }

    # 3. Build aggregations for each timeframe
    results = {}

    for key, (label, start, end) in timeframes.items():
        gas_aggs = {}

        # Main alarm aggregation across all included gas/emergency alarms.
        alarms_agg, _, _, loc_scores = build_alarm_h3_agg(
            mapped_df=vis_df,
            customer_id=customer_id,
            h3_res=h3_res,
            start_time=start,
            end_time=end,
            gas_type="all",
            full_session_df=customer,
            score_df=loc_score
        )

        gas_aggs["all"] = alarms_agg

        # Gas-specific layers used by the gas subtype selector.
        for gas_type in ["co", "h2s", "o2", "comb"]:
            gas_aggs[gas_type], _, _, _ = build_alarm_h3_agg(
                mapped_df=vis_df,
                customer_id=customer_id,
                h3_res=h3_res,
                start_time=start,
                end_time=end,
                gas_type=gas_type,
                full_session_df=customer,
                score_df=loc_score
            )

        visited_agg = build_visited_h3_agg(
            df_locations=customer_location,
            customer_id=customer_id,
            h3_res=h3_res,
            start_time=start,
            end_time=end
        )

        results[key] = {
            "label": label,
            "alarms_agg": alarms_agg,
            "gas_aggs": gas_aggs,
            "loc_scores": loc_scores,
            "visited_agg": visited_agg,
        }

    # 4. Initialize map
    center_df = results["all"]["alarms_agg"]
    center = [center_df["lat"].median(), center_df["lon"].median()]
    # Note: "tiles" can be changed to "CartoDB Voyager" if OpenStreetMap causes issues
    m = folium.Map(location=center, zoom_start=13, tiles="OpenStreetMap")

    # 5. Add timeframe-specific map layers
    bundle_registry = {}

    for key, result in results.items():
        bundle_registry[key] = build_timeframe_bundle(
            m=m,
            alarms_agg=result["alarms_agg"],
            timeframe_key=key,
            timeframe_label=result["label"],
            h3_res=h3_res,
            gas_aggs=result["gas_aggs"],
            loc_score_summary=result["loc_scores"],
            visited_agg=result["visited_agg"]
        )

    # 6. Add map UI controls
    add_shared_risk_legend(m)
    add_dynamic_info_box(m)
    add_selector_ui(m)
    add_toggle_script(m, bundle_registry)

    # 7. Save and return
    m.save(output_file)
    print(f"Heatmap saved to: {output_file}")
    return m
