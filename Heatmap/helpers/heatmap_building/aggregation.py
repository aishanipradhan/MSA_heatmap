import pandas as pd
import numpy as np
import h3
from .location_matching import assign_locations_to_alarms


# Alarm category definitions
GAS_ALARMS = [
    "ALARM_GAS_EXPOSURE",
    "ALARM_GAS_DEFICIENCY",
    "ALARM_GAS_STEL",
    "ALARM_GAS_TWA",
    "ALARM_GAS_OVERRANGE",
    "ALARM_GAS_UNDERRANGE",
]

EMERGENCY_ALARMS = [
    "ALARM_WORKER_EMERGENCY",
    "ALARM_NOMOTION",
    "ALARM_NOMOTION_NORESPONSE",
    "ALARM_REMOTE_EVACUATION",
    "ALARM_CHECKIN_NORESPONSE",
]

INCLUDED_ALARMS = GAS_ALARMS + EMERGENCY_ALARMS


# Gas type filters used by the map UI
GAS_TYPE_MAP = {
    "all": None,
    "co": "GAS_TYPE_CARBON_MONOXIDE",
    "h2s": "GAS_TYPE_HYDROGEN_SULFIDE",
    "o2": "GAS_TYPE_OXYGEN",
    "comb": "GAS_TYPE_COMBUSTIBLE",
}

# User-friendly labels for tooltip display
GAS_LABEL_MAP = {
    "GAS_TYPE_CARBON_MONOXIDE": "Carbon Monoxide",
    "GAS_TYPE_HYDROGEN_SULFIDE": "Hydrogen Sulfide",
    "GAS_TYPE_OXYGEN": "Oxygen",
    "GAS_TYPE_COMBUSTIBLE": "Combustible",
}


def _filter_customer_window(df, customer_id, start_time=None, end_time=None, time_col="LOGGED_AT"):
    """
    Filter a dataframe to one customer and an optional time window.

    Parameters
    ----------
    df : pd.DataFrame
        Input event/session dataframe.

    customer_id : str
        Customer ID to keep.

    start_time : str or datetime, optional
        Keep rows with time_col >= start_time.

    end_time : str or datetime, optional
        Keep rows with time_col <= end_time.

    time_col : str
        Timestamp column used for filtering.

    Returns
    -------
    pd.DataFrame
        Filtered dataframe.
    """
    out = df.copy()
    out[time_col] = pd.to_datetime(out[time_col], errors="coerce")

    out = out[out["CUSTOMER_ID"] == customer_id].copy()

    if start_time is not None:
        start_time = pd.to_datetime(start_time)
        out = out[out[time_col] >= start_time].copy()

    if end_time is not None:
        end_time = pd.to_datetime(end_time)
        out = out[out[time_col] <= end_time].copy()

    return out


def build_score_session_df(score_df, customer_id, start_time=None, end_time=None):
    """
    Build a session-level location-score dataframe for one customer.

    This function keeps one row per SESSION_ID and optionally filters sessions
    by whether their session interval overlaps with the selected time window.

    Parameters
    ----------
    score_df : pd.DataFrame
        Dataframe containing session-level or event-level location scores.

    customer_id : str
        Customer ID to keep.

    start_time : str or datetime, optional
        Start of selected time window.

    end_time : str or datetime, optional
        End of selected time window.

    Returns
    -------
    pd.DataFrame
        Session-level dataframe with:
        - SESSION_ID
        - CUSTOMER_ID
        - location_score
        - optional session metadata columns
    """
    df = score_df.copy()

    # Convert available time columns to datetime.
    for col in ["start_time", "end_time", "LOGGED_AT"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    df = df[df["CUSTOMER_ID"] == customer_id].copy()

    keep_cols = ["SESSION_ID", "CUSTOMER_ID", "location_score"]
    optional_cols = ["start_time", "end_time", "session_has_locations"]
    keep_cols += [col for col in optional_cols if col in df.columns]

    # Keep one row per session.
    session_df = df[keep_cols].drop_duplicates("SESSION_ID").copy()
    session_df["location_score"] = pd.to_numeric(
        session_df["location_score"],
        errors="coerce"
    )

    # Keep sessions that overlap the selected time window.
    if start_time is not None and "end_time" in session_df.columns:
        start_time = pd.to_datetime(start_time)
        session_df = session_df[session_df["end_time"] >= start_time].copy()

    if end_time is not None and "start_time" in session_df.columns:
        end_time = pd.to_datetime(end_time)
        session_df = session_df[session_df["start_time"] <= end_time].copy()

    return session_df


def valid_coordinate_mask(df):
    return (
        df["latitude"].notna()
        & df["longitude"].notna()
        & df["latitude"].between(-90, 90)
        & df["longitude"].between(-180, 180)
        & (df["latitude"] != 214.748365)
        & (df["longitude"] != 214.748365)
    )


def build_alarm_h3_agg(
    mapped_df,
    customer_id,
    h3_res=9,
    start_time=None,
    end_time=None,
    included_alarms=None,
    gas_type="all",
    full_session_df=None,
    score_df=None,
    verbose=False,
):
    """
    Build H3-level alarm aggregation for one customer.

    This function:
    1. Filters data to one customer and optional time window.
    2. Keeps only included alarm types.
    3. Optionally filters gas alarms by gas type.
    4. Matches each alarm to the nearest location ping in the same session.
    5. Converts alarm and location coordinates into H3 cells.
    6. Aggregates alarm metrics by H3 cell.
    7. Builds summary statistics for the map info box.

    Parameters
    ----------
    mapped_df : pd.DataFrame
        Event-level dataframe used for alarm/location mapping.
        Should contain LOCATION and ALARM rows.

    customer_id : str
        Customer ID to build aggregation for.

    h3_res : int
        H3 resolution.

    start_time : str or datetime, optional
        Start of selected time window.

    end_time : str or datetime, optional
        End of selected time window.

    included_alarms : list, optional
        Alarm types to include. Defaults to INCLUDED_ALARMS.

    gas_type : str
        Gas filter. Options: "all", "co", "h2s", "o2", "comb".

    full_session_df : pd.DataFrame, optional
        Full customer dataset used only for total session counts.

    score_df : pd.DataFrame, optional
        Dataframe containing location_score used for summary statistics.

    verbose : bool
        If True, print debug / sanity-check messages.

    Returns
    -------
    tuple
        alarms_agg : pd.DataFrame
            H3-level alarm aggregation.

        df_alarms_located : pd.DataFrame
            Alarm events after nearest-location matching.

        df_locations : pd.DataFrame
            Location events with valid coordinates and H3 cells.

        loc_score_summary : dict
            Summary values for the map info box.
    """
    if included_alarms is None:
        included_alarms = INCLUDED_ALARMS

    empty_cols = [
        "h3_cell", "n_sessions_w_alarms", "n_alarm_days",
        "n_gas_alarms", "n_emg_alarms", "alarm_types",
        "total_sessions", "lat", "lon",
        "w_sessions", "w_gas", "w_emg", "w_repeat",
    ]

    empty_summary = {
        "total_sessions": 0,
        "sessions_w_alarms": 0,
        "mapped_alarm_sessions": 0,
        "score_0": 0,
        "score_1": 0,
        "score_2": 0,
        "score_3": 0,
        "score_4": 0,
    }

    # 1. Filter main event data
    customer_df = _filter_customer_window(
        mapped_df,
        customer_id=customer_id,
        start_time=start_time,
        end_time=end_time,
        time_col="LOGGED_AT",
    )

    # Full session dataset is used only for total session count.
    if full_session_df is None:
        full_customer_df = customer_df
    else:
        full_customer_df = _filter_customer_window(
            full_session_df,
            customer_id=customer_id,
            start_time=start_time,
            end_time=end_time,
            time_col="LOGGED_AT",
        )

    # Score dataset is used only for location-score summary.
    if score_df is None:
        score_customer_df = pd.DataFrame(columns=["SESSION_ID", "location_score"])
    else:
        score_customer_df = build_score_session_df(
            score_df=score_df,
            customer_id=customer_id,
            start_time=start_time,
            end_time=end_time,
        )

    # 2. Filter alarm and location events
    df_alarms = customer_df[
        (customer_df["EVENT_TYPE"] == "ALARM")
        & (customer_df["META_ALARM"].isin(included_alarms))
    ].copy()

    if gas_type != "all":
        gas_value = GAS_TYPE_MAP[gas_type]
        df_alarms = df_alarms[df_alarms["META_GAS"] == gas_value].copy()

    df_locations = customer_df[(customer_df["EVENT_TYPE"] == "LOCATION")
                               & valid_coordinate_mask(customer_df)].copy()

    if verbose:
        print(f"Location pings: {len(df_locations)}")
        print(f"Alarm events: {len(df_alarms)}")
        print(f"Sessions with locations: {df_locations['SESSION_ID'].nunique()}")
        print(f"Sessions with alarms: {df_alarms['SESSION_ID'].nunique()}")

    if df_alarms.empty or df_locations.empty:
        if verbose:
            print("No alarm/location data available for this filter window.")

        return (
            pd.DataFrame(columns=empty_cols),
            pd.DataFrame(),
            pd.DataFrame(),
            empty_summary,
        )

    # 3. Match alarms to nearest location pings
    df_alarms_located = assign_locations_to_alarms(
        df_alarms,
        df_locations,
        verbose=verbose,
    ).copy()

    # Keep only rows with valid coordinates.
    df_alarms_located = df_alarms_located[
        valid_coordinate_mask(df_alarms_located)
    ].copy()

    df_locations = df_locations[
        valid_coordinate_mask(df_locations)
    ].copy()

    if df_alarms_located.empty or df_locations.empty:
        if verbose:
            print("No valid coordinates available after filtering.")

        return (
            pd.DataFrame(columns=empty_cols),
            pd.DataFrame(),
            pd.DataFrame(),
            empty_summary,
        )

    # 4. Convert coordinates to H3 cells
    df_alarms_located["h3_cell"] = [
        h3.latlng_to_cell(lat, lng, h3_res)
        for lat, lng in zip(
            df_alarms_located["latitude"],
            df_alarms_located["longitude"],
        )
    ]

    df_locations["h3_cell"] = [
        h3.latlng_to_cell(lat, lng, h3_res)
        for lat, lng in zip(
            df_locations["latitude"],
            df_locations["longitude"],
        )
    ]

    # Exposure denominator: number of visited sessions per H3 cell.
    total_exposure = (
        df_locations
        .groupby("h3_cell", as_index=False)
        .agg(total_sessions=("SESSION_ID", "nunique"))
    )

    # 5. Aggregate alarm metrics by H3 cell
    alarms_agg = (
        df_alarms_located
        .groupby("h3_cell", as_index=False)
        .agg(
            n_sessions_w_alarms=("SESSION_ID", "nunique"),
            n_alarm_days=("LOGGED_AT", lambda x: x.dt.date.nunique()),
            n_gas_alarms=("META_ALARM", lambda x: x.isin(GAS_ALARMS).sum()),
            n_emg_alarms=("META_ALARM", lambda x: x.isin(EMERGENCY_ALARMS).sum()),
            alarm_types=("META_ALARM", lambda x: sorted(pd.Series(x.dropna().unique()).tolist())),
            gas_types_present=("META_GAS", lambda x: sorted({
                GAS_LABEL_MAP.get(v, v)
                for v in x.dropna().unique()
                if v in GAS_LABEL_MAP
            })),
            n_gas_co=("META_GAS", lambda x: (x == "GAS_TYPE_CARBON_MONOXIDE").sum()),
            n_gas_h2s=("META_GAS", lambda x: (x == "GAS_TYPE_HYDROGEN_SULFIDE").sum()),
            n_gas_o2=("META_GAS", lambda x: (x == "GAS_TYPE_OXYGEN").sum()),
            n_gas_comb=("META_GAS", lambda x: (x == "GAS_TYPE_COMBUSTIBLE").sum()),
        )
    )

    alarms_agg = alarms_agg.merge(total_exposure, on="h3_cell", how="left")
    alarms_agg["total_sessions"] = alarms_agg["total_sessions"].fillna(0).astype(int)

    # Add H3 cell center coordinates for heatmap rendering.
    centers = alarms_agg["h3_cell"].apply(h3.cell_to_latlng)
    alarms_agg["lat"] = centers.str[0]
    alarms_agg["lon"] = centers.str[1]

    # 6. Normalize metrics for heatmap intensity
    def safe_log_norm(series):
        """
        Log-normalize a numeric series to the range [0, 1].

        log1p compresses extreme values so that very high-count cells
        do not dominate the heatmap.
        """
        series = pd.to_numeric(series, errors="coerce").fillna(0)
        log_vals = np.log1p(series)
        max_val = log_vals.max()

        if max_val > 0:
            return log_vals / max_val

        return pd.Series(0, index=series.index)

    alarms_agg["w_sessions"] = safe_log_norm(alarms_agg["n_sessions_w_alarms"])
    alarms_agg["w_gas"] = safe_log_norm(alarms_agg["n_gas_alarms"])
    alarms_agg["w_emg"] = safe_log_norm(alarms_agg["n_emg_alarms"])
    alarms_agg["w_repeat"] = safe_log_norm(alarms_agg["n_alarm_days"])

    # 7. Build location-score summary
    total_sessions = int(full_customer_df["SESSION_ID"].nunique())
    alarm_sessions = int(score_customer_df["SESSION_ID"].nunique())

    mapped_alarm_sessions = int(
        score_customer_df.loc[
            score_customer_df["location_score"].isin([2, 3, 4]),
            "SESSION_ID",
        ].nunique()
    )

    score_counts = score_customer_df["location_score"].value_counts().to_dict()

    loc_score_summary = {
        "total_sessions": total_sessions,
        "sessions_w_alarms": alarm_sessions,
        "mapped_alarm_sessions": mapped_alarm_sessions,
        "score_0": int(score_counts.get(0, 0)),
        "score_1": int(score_counts.get(1, 0)),
        "score_2": int(score_counts.get(2, 0)),
        "score_3": int(score_counts.get(3, 0)),
        "score_4": int(score_counts.get(4, 0)),
    }

    return alarms_agg, df_alarms_located, df_locations, loc_score_summary


def build_visited_h3_agg(
    df_locations,
    customer_id,
    h3_res=9,
    start_time=None,
    end_time=None,
):
    """
    Build H3 aggregation for visited locations without alarm visualization.

    This is used for the gray "Visited" layer.

    Parameters
    ----------
    df_locations : pd.DataFrame
        Location event dataframe.

    customer_id : str
        Customer ID to keep.

    h3_res : int
        H3 resolution.

    start_time : str or datetime, optional
        Start of selected time window.

    end_time : str or datetime, optional
        End of selected time window.

    Returns
    -------
    pd.DataFrame
        H3-level visited-location aggregation with:
        - h3_cell
        - n_sessions_visited
        - n_location_pings
        - lat
        - lon
        - w_visited
    """
    customer_df = _filter_customer_window(
        df_locations,
        customer_id=customer_id,
        start_time=start_time,
        end_time=end_time,
        time_col="LOGGED_AT",
    )

    customer_df = customer_df[valid_coordinate_mask(customer_df)].copy()

    if customer_df.empty:
        return pd.DataFrame(columns=[
            "h3_cell",
            "n_sessions_visited",
            "n_location_pings",
            "lat",
            "lon",
            "w_visited",
        ])

    customer_df = customer_df.copy()

    customer_df["h3_cell"] = [
        h3.latlng_to_cell(lat, lng, h3_res)
        for lat, lng in zip(
            customer_df["latitude"],
            customer_df["longitude"],
        )
    ]

    visited_agg = (
        customer_df
        .groupby("h3_cell", as_index=False)
        .agg(
            n_sessions_visited=("SESSION_ID", "nunique"),
            n_location_pings=("SESSION_ID", "size"),
        )
    )

    centers = visited_agg["h3_cell"].apply(h3.cell_to_latlng)
    visited_agg["lat"] = centers.str[0]
    visited_agg["lon"] = centers.str[1]

    max_val = visited_agg["n_sessions_visited"].max()
    visited_agg["w_visited"] = (
        visited_agg["n_sessions_visited"] / max_val
        if max_val > 0
        else 0
    )

    return visited_agg
