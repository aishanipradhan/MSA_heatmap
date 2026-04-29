import folium
from folium.plugins import HeatMap
import h3


RISK_GRADIENT = {
    0.00: '#FFFDE7',
    0.15: '#FFF176',
    0.35: '#FFD54F',
    0.55: '#FFB300',
    0.75: '#F57C00',
    1.00: '#C62828'
}


def build_timeframe_bundle(
    m,
    alarms_agg,
    timeframe_key,
    timeframe_label,
    h3_res=9,
    heat_radius=25,
    heat_blur=14,
    heat_min_opacity=0.6,
    gas_aggs=None,
    loc_score_summary=None,
    visited_agg=None,
    verbose=False
):
    """
    Add all map layers for one timeframe and return a registry bundle.

    This function creates:
    - visited-only gray hexagon layer
    - heatmap layers for alarm sessions, gas alarms, emergency alarms, and repeat alarm days
    - transparent alarm hexagon layer with hover tooltips
    - summary statistics used by the custom info box

    Parameters
    ----------
    m : folium.Map
        Existing Folium map object to add layers to.

    alarms_agg : pd.DataFrame
        H3-level alarm aggregation created by build_alarm_h3_agg().

    timeframe_key : str
        Short internal key for the timeframe, such as "2w", "1m", or "all".

    timeframe_label : str
        Display label for the timeframe, such as "Last 2 Weeks".

    h3_res : int
        H3 resolution used for the aggregation.

    heat_radius : int
        Radius parameter for Folium HeatMap.

    heat_blur : int
        Blur parameter for Folium HeatMap.

    heat_min_opacity : float
        Minimum opacity for Folium HeatMap.

    gas_aggs : dict, optional
        Dictionary of gas-specific H3 aggregations.
        Expected keys: "all", "co", "h2s", "o2", "comb".

    loc_score_summary : dict, optional
        Summary statistics for the dynamic info box.

    visited_agg : pd.DataFrame, optional
        H3-level visited-location aggregation for the gray layer.

    verbose : bool
        If True, print debug messages.

    Returns
    -------
    dict
        Bundle containing layer references and summary data.
        Used later by add_toggle_script().
    """
    bundle = {
        "label": timeframe_label,
        "metrics": {},
        "hex": None,
        "visited_hex": None,
        "summary": {}
    }

    if alarms_agg.empty:
        if verbose:
            print(f"[{timeframe_label}] alarms_agg is empty. Skipping.")
        return bundle

    if gas_aggs is None:
        gas_aggs = {"all": alarms_agg}

    if loc_score_summary is None:
        loc_score_summary = {}

    def add_heat_layer(name, df, value_col, metric_key, show=False, filter_mask=None):
        """
        Add one HeatMap layer to the Folium map and register it in the bundle.
        """
        fg = folium.FeatureGroup(name=name, show=show)

        if df is not None and not df.empty:
            plot_df = df if filter_mask is None else df.loc[filter_mask]
            if not plot_df.empty:
                HeatMap(
                    data=plot_df[['lat', 'lon', value_col]].values.tolist(),
                    min_opacity=heat_min_opacity,
                    radius=heat_radius,
                    blur=heat_blur,
                    gradient=RISK_GRADIENT,
                    show=True
                ).add_to(fg)

        fg.add_to(m)
        bundle["metrics"][metric_key] = fg
        return fg

    def make_hex_feature(row, properties):
        """
        Convert one H3 cell row into a GeoJSON polygon feature.
        """
        boundary = h3.cell_to_boundary(row['h3_cell'])
        coordinates = [[lon, lat] for lat, lon in boundary]
        coordinates.append(coordinates[0])

        return {
            'type': 'Feature',
            'geometry': {'type': 'Polygon', 'coordinates': [coordinates]},
            'properties': properties
        }

    # Visited-only hex layer
    visited_hex_fg = folium.FeatureGroup(
        name=f"{timeframe_label} | Visited (No Alarms Observed)",
        show=True
    )

    if visited_agg is not None and not visited_agg.empty:
        visited_features = [
            make_hex_feature(
                row,
                {
                    'h3_cell': row['h3_cell'],
                    'n_sessions_visited': int(row['n_sessions_visited']),
                    'n_location_pings': int(row['n_location_pings']),
                }
            )
            for _, row in visited_agg.iterrows()
        ]

        visited_geojson = {'type': 'FeatureCollection', 'features': visited_features}

        folium.GeoJson(
            visited_geojson,
            style_function=lambda feature: {
                'fillColor': '#9E9E9E',
                'color': "#757575",
                'weight': 0.5,
                'fillOpacity': 0.3,
                'opacity': 0.75,
            },
            highlight_function=lambda feature: {
                'fillColor': "#757575",
                'color': "#616161",
                'weight': 1.0,
                'fillOpacity': 0.4,
                'opacity': 0.8,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['h3_cell', 'n_sessions_visited', 'n_location_pings'],
                aliases=['H3 Cell:', 'Visited sessions:', 'Location pings:'],
                localize=True,
                sticky=True,
                style='font-family: Arial, Helvetica, sans-serif; font-size: 12px;'
            )
        ).add_to(visited_hex_fg)

    visited_hex_fg.add_to(m)
    bundle["visited_hex"] = visited_hex_fg

    # Heatmap layers
    add_heat_layer(
        name=f"{timeframe_label} | Sessions",
        df=alarms_agg,
        value_col='w_sessions',
        metric_key='sessions',
        show=False
    )

    gas_key_map = {
        "all": ("gas_all", "Gas All"),
        "co": ("gas_co", "Gas CO"),
        "h2s": ("gas_h2s", "Gas H2S"),
        "o2": ("gas_o2", "Gas O2"),
        "comb": ("gas_comb", "Gas Combustible"),
    }

    for short_key, (metric_key, label) in gas_key_map.items():
        gas_df = gas_aggs.get(short_key)
        add_heat_layer(
            name=f"{timeframe_label} | {label}",
            df=gas_df,
            value_col='w_gas',
            metric_key=metric_key,
            show=False
        )

    add_heat_layer(
        name=f"{timeframe_label} | Emergency",
        df=alarms_agg,
        value_col='w_emg',
        metric_key='emg',
        show=False,
        filter_mask=alarms_agg['n_emg_alarms'] > 0
    )

    add_heat_layer(
        name=f"{timeframe_label} | Repeat",
        df=alarms_agg,
        value_col='w_repeat',
        metric_key='repeat',
        show=False
    )

    # Alarm hexagons
    hex_fg = folium.FeatureGroup(name=f"{timeframe_label} | Hexagons", show=True)

    alarms_hex_df = alarms_agg.copy()

    alarms_hex_df = alarms_hex_df.drop(
        columns=["n_sessions_visited", "n_location_pings"],
        errors="ignore"
    )

    if visited_agg is not None and not visited_agg.empty:
        visited_for_merge = visited_agg[
            ["h3_cell", "n_sessions_visited", "n_location_pings"]
        ].copy()

        alarms_hex_df = alarms_hex_df.merge(
            visited_for_merge,
            on="h3_cell",
            how="left"
        )

    for col in ["n_sessions_visited", "n_location_pings"]:
        if col not in alarms_hex_df.columns:
            alarms_hex_df[col] = 0
        alarms_hex_df[col] = alarms_hex_df[col].fillna(0).astype(int)

    features = []
    for _, row in alarms_hex_df.iterrows():
        alarm_types_str = (
            '<br>'.join(a.replace('ALARM_', '') for a in row['alarm_types'])
            if row['alarm_types'] else 'N/A'
        )
        gas_types_str = (
            '<br>'.join(row['gas_types_present'])
            if row['gas_types_present'] else 'N/A'
        )

        features.append(
            make_hex_feature(
                row,
                {
                    'h3_cell': row['h3_cell'],
                    'n_sessions_w_alarms': int(row['n_sessions_w_alarms']),
                    'n_alarm_days': int(row['n_alarm_days']),
                    'n_gas_alarms': int(row['n_gas_alarms']),
                    'n_emg_alarms': int(row['n_emg_alarms']),
                    'alarm_types': alarm_types_str,
                    'gas_types_present': gas_types_str,
                    'n_gas_co': int(row['n_gas_co']),
                    'n_gas_h2s': int(row['n_gas_h2s']),
                    'n_gas_o2': int(row['n_gas_o2']),
                    'n_gas_comb': int(row['n_gas_comb']),
                    'n_sessions_visited': int(row['n_sessions_visited']),
                    'n_location_pings': int(row['n_location_pings']),
                }
            )
        )

    geojson = {'type': 'FeatureCollection', 'features': features}

    folium.GeoJson(
        geojson,
        style_function=lambda feature: {
            'fillColor': 'transparent',
            'color': '#ACA59D',
            'weight': 1,
            'fillOpacity': 0,
            'opacity': 0.8,
        },
        highlight_function=lambda feature: {
            'fillColor': '#FFD700',
            'color': '#6B6B6B',
            'weight': 2.2,
            'fillOpacity': 0.25,
            'opacity': 1.0,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=[
                'h3_cell',
                'n_sessions_w_alarms',
                'n_alarm_days',
                'n_gas_alarms',
                'n_emg_alarms',
                'alarm_types',
                'n_gas_co',
                'n_gas_h2s',
                'n_gas_o2',
                'n_gas_comb',
                'gas_types_present',
                'n_sessions_visited',
                'n_location_pings',
            ],
            aliases=[
                'H3 Cell:',
                'Sessions with Alarms:',
                'Alarm days:',
                'Gas alarms:',
                'Emergency alarms:',
                'Alarm types:',
                'CO alarms:',
                'H2S alarms:',
                'O2 alarms:',
                'Combustible alarms:',
                'Gas types present:',
                'Visited sessions:',
                'Location pings:',
            ],
            localize=True,
            sticky=True,
            style='font-family: Arial, Helvetica, sans-serif; font-size: 12px;'
        )
    ).add_to(hex_fg)

    hex_fg.add_to(m)
    bundle["hex"] = hex_fg

    # Cell-count summary
    alarm_cells = int(len(alarms_agg))
    if visited_agg is not None and not visited_agg.empty:
        alarm_cell_set = set(alarms_agg['h3_cell'])
        visited_only_cells = int((~visited_agg['h3_cell'].isin(alarm_cell_set)).sum())
    else:
        visited_only_cells = 0
    total_cells_shown = alarm_cells + visited_only_cells

    # Summary
    bundle["summary"] = {
        "label": timeframe_label,
        "h3_res": h3_res,
        "alarm_cells": alarm_cells,
        "visited_only_cells": visited_only_cells,
        "total_sessions": loc_score_summary.get("total_sessions", 0),
        "sessions_w_alarms": loc_score_summary.get("sessions_w_alarms", 0),
        "mapped_alarm_sessions": loc_score_summary.get("mapped_alarm_sessions", 0),
        "loc_score_0": loc_score_summary.get("score_0", 0),
        "loc_score_1": loc_score_summary.get("score_1", 0),
        "loc_score_2": loc_score_summary.get("score_2", 0),
        "loc_score_3": loc_score_summary.get("score_3", 0),
        "loc_score_4": loc_score_summary.get("score_4", 0),
    }

    return bundle
