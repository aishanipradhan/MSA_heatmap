import numpy as np
import pandas as pd

from .filtering_helper import filter_target_alarm_sessions
from .session_length_helper import session_length_alarms


def gap_fraction_fast(loc_s, alarm_s):
    """
    Compute the fraction of alarms that occur far from any location ping.

    For each alarm timestamp, the function finds the closest location timestamp
    and measures the time difference. If this difference exceeds a dynamically
    defined threshold, the alarm is considered to fall within a "large gap".

    The gap threshold is defined as:
        max(30 minutes, 2 × median gap between consecutive location pings)

    Parameters
    ----------
    loc_s : pandas.DataFrame
        DataFrame containing location ping events for a single session.
        Must include a "LOGGED_AT" column of datetime-like values.
        Assumed to contain only location-related events.

    alarm_s : pandas.DataFrame
        DataFrame containing alarm events for the same session.
        Must include a "LOGGED_AT" column of datetime-like values.
        Assumed to contain only alarm-related events.
        
    Returns
    ----------
    float or np.nan
        Fraction of alarms that fall in large gaps (no nearby location data).
        Returns np.nan if there are fewer than 2 location points or no alarms.
    """

    # Not enough data to compute gaps or no alarms to evaluate
    if len(loc_s) < 2 or len(alarm_s) == 0:
        return np.nan

    # Extract location timestamps and compute gaps between consecutive points (in seconds)
    times = loc_s["LOGGED_AT"].values
    gaps = np.diff(times).astype("timedelta64[s]").astype(int)

    # Define adaptive threshold based on data density
    median_gap = np.median(gaps)
    gap_threshold = max(30 * 60, 2 * median_gap)

    large = 0
    alarm_times = alarm_s["LOGGED_AT"].values

    # For each alarm, compute distance to nearest location timestamp
    for t in alarm_times:
        diff = np.min(np.abs(times - np.datetime64(t))).astype(
            "timedelta64[s]"
        ).astype(int)

        # Count alarms that fall outside acceptable proximity
        if diff > gap_threshold:
            large += 1

    # Return fraction of alarms in large gaps
    return large / len(alarm_times)


def concentration_fast(times, window_minutes):
    """
    Measure how concentrated timestamps are within a time window.

    For each timestamp, the function counts how many other timestamps fall
    within a symmetric window around it and tracks the maximum count.
    This maximum reflects the strongest clustering.

    The score is defined as:
        max_count / total_points

    Interpretation:
    - Values close to 1: timestamps are highly concentrated
    - Values close to 0: timestamps are well spread out

        Parameters
    ----------
    times : array-like of datetime64
        Sequence of timestamps (e.g., numpy array or pandas Series) for a
        single session or event type. Must be comparable using vectorized
        datetime operations.

    window_minutes : int or float
        Size of the symmetric time window (in minutes) used to evaluate
        local concentration around each timestamp.

    Returns
    ----------
    float or np.nan
        Score between 0 and 1. Returns np.nan if no timestamps are provided.
    """

    n = len(times)

    # No timestamps lead to an undefined metric
    if n == 0:
        return np.nan

    # Convert window size to timedelta
    window = np.timedelta64(window_minutes, "m")

    max_count = 0

    # For each timestamp, count how many fall within the local window
    for t in times:
        count = np.sum((times >= t - window) & (times <= t + window))
        max_count = max(max_count, count)

    # Higher max_count means higher concentration score
    return max_count / n


def score_with_reasons(row):
    """
    Assign a location score to a session based on location signal metrics,
    along with reasons explaining any penalties.

    The scoring logic combines multiple signals:
    - pct_valid_gps: fraction of valid GPS points
    - concentration_window: degree of concentration of timestamps
    - density: number of valid locations per hour
    - large_gap_fraction: fraction of alarms far from location data

    Scoring rules:
    - 0: no location data or missing key metrics
    - 1: severe issues (very low GPS validity or very low concentration)
    - 2: moderate issues (below baseline density, gaps, moderate concentration/GPS issues)
    - 3: acceptable (default case)
    - 4: high quality (meets all strong thresholds)

    Parameters
    ----------
    row : pandas.Series or dict-like
        A single session record containing the following fields:
        - session_has_locations : str
            "yes" or "no" indicating whether any location data exists.
        - density : float
            Number of valid location points per hour.
        - baseline_density : float
            Reference density threshold used for comparison.
        - pct_valid_gps : float
            Fraction of GPS points that are valid (between 0 and 1).
        - concentration_window : float
            Concentration score (between 0 and 1), where higher values
            indicate more clustering of timestamps.
        - large_gap_fraction : float
            Fraction of alarms occurring far from any location data (between 0 and 1).
            
    Returns:
    ----------
    tuple
        (score, reasons)
        score : int
            Integer score from 0 to 4.
        reasons : list of str
            List of rule violations contributing to the score.
    """

    reasons = []

    # No location data at all
    if row["session_has_locations"] == "no":
        return 0, ["no_locations"]

    # If there are missing critical metrics, assign 0
    if (
        pd.isna(row["density"])
        or pd.isna(row["pct_valid_gps"])
        or pd.isna(row["concentration_window"])
    ):
        return 0, ["missing_metrics"]

    # Collect rule violations for interpretability
    if row["pct_valid_gps"] < 0.3:
        reasons.append("pct_valid_gps<0.3")

    if row["concentration_window"] > 0.8:
        reasons.append("concentration>0.8")

    if row["density"] < row["baseline_density"]:
        reasons.append("density<baseline")

    if row["large_gap_fraction"] > 0.5:
        reasons.append("gap>0.5")

    if 0.6 < row["concentration_window"] <= 0.8:
        reasons.append("concentration>0.6")

    if row["pct_valid_gps"] < 0.5:
        reasons.append("pct_valid_gps<0.5")

    # Assign score
    if row["pct_valid_gps"] < 0.3 or row["concentration_window"] > 0.8:
        score = 1
    elif (
        row["density"] < row["baseline_density"]
        or row["large_gap_fraction"] > 0.5
        or (0.6 < row["concentration_window"] <= 0.8)
        or row["pct_valid_gps"] < 0.5
    ):
        score = 2
    elif (
        row["density"] >= row["baseline_density"]
        and row["large_gap_fraction"] == 0
        and row["concentration_window"] <= 0.3
        and row["pct_valid_gps"] >= 0.8
    ):
        score = 4
    else:
        score = 3

    return score, reasons


def location_validation(events, window_minutes=15):
    """
    Compute location quality scores for each session and attach them to all
    events.

    Metrics are used to assign a location score and corresponding
    reasons via `score_with_reasons`.

    Parameters
    ----------
    events : pandas.DataFrame
        Input events dataset containing session-level telemetry. Must include
        the following columns:
        - SESSION_ID : identifier for each session
        - CUSTOMER_ID : identifier for customer
        - EVENT_TYPE : type of event (e.g., "ALARM", "LOCATION", "MODE")
        - META_TYPE : subtype of event (used for filtering alarms)
        - META_MODE : operating mode (used in session windowing)
        - LOGGED_AT : timestamp of the event (datetime-like)
        - gps_valid : boolean indicating whether a location point is valid

        Note:
        The function internally filters to sessions containing target alarms
        using `filter_target_alarm_sessions`. While this is expected to be
        done upstream, it is repeated here as a safeguard.

    window_minutes : int or float, default=15
        Size of the symmetric time window (in minutes) used when computing
        the concentration metric for location timestamps.

    Returns
    ----------
    pandas.DataFrame
        Original events DataFrame with additional session-level columns:
        - density
        - pct_valid_gps
        - large_gap_fraction
        - concentration_window
        - location_score
        - location_score_reasons
    """

    # Filter to only sessions containing relevant (target) alarms
    # This should ideally be done before the location validation function is called, but we include it here for safety
    df = filter_target_alarm_sessions(events)

    # Select relevant columns for processing
    df = df[
        [
            "SESSION_ID",
            "CUSTOMER_ID",
            "EVENT_TYPE",
            "META_TYPE",
            "META_MODE",
            "LOGGED_AT",
            "gps_valid",
        ]
    ].copy()

    # Ensure proper data types
    df["LOGGED_AT"] = pd.to_datetime(df["LOGGED_AT"])
    df["gps_valid"] = df["gps_valid"].map({True: 1, False: 0})

    # Extract alarm events (after filtering, all alarms are target alarms)
    alarms = df[df["EVENT_TYPE"] == "ALARM"].copy()

    # Sessions that contain alarms
    alarm_sessions = set(alarms["SESSION_ID"])
    df = df[df["SESSION_ID"].isin(alarm_sessions)].copy()

    # Recompute alarms after filtering sessions
    alarms = df[df["EVENT_TYPE"] == "ALARM"].copy()

    # Separate location events and valid GPS points
    loc = df[df["EVENT_TYPE"] == "LOCATION"].copy()
    loc_valid = loc[loc["gps_valid"] == 1].copy()

    # Count total location events per session
    loc_total = (
        loc.groupby("SESSION_ID")
        .size()
        .reset_index(name="n_loc_total")
    )

    # Compute fraction of valid GPS points per session
    gps_pct = (
        loc.groupby("SESSION_ID")["gps_valid"]
        .mean()
        .reset_index(name="pct_valid_gps")
    )

    # Combine location counts and GPS validity
    loc_present = loc_total.merge(gps_pct, on="SESSION_ID", how="outer")

    # Ensure numeric type for GPS percentage
    loc_present["pct_valid_gps"] = pd.to_numeric(
        loc_present["pct_valid_gps"], errors="coerce"
    )

    # Flag sessions with no usable location data
    loc_present["session_has_locations"] = np.where(
        (loc_present["n_loc_total"].fillna(0) == 0)
        | (loc_present["pct_valid_gps"].fillna(0) == 0),
        "no",
        "yes",
    )

    # Compute session duration using alarm timestamps
    session_time = session_length_alarms(df)

    # Count valid location points per session
    loc_counts = (
        loc_valid.groupby("SESSION_ID")
        .size()
        .reset_index(name="n_locations")
    )

    # Compute density of valid locations per hour
    density = session_time.merge(loc_counts, on="SESSION_ID", how="left")
    density["density"] = density["n_locations"] / density["duration_hr"]

    # Attach customer information
    session_customer = df[["SESSION_ID", "CUSTOMER_ID"]].drop_duplicates()
    density = density.merge(session_customer, on="SESSION_ID")

    # Define baseline expected density
    baseline = 15
    density["baseline_density"] = baseline

    gap_list = []
    concentration_list = []

    # Sort valid locations for per-session computations
    loc_valid_sorted = loc_valid.sort_values(["SESSION_ID", "LOGGED_AT"])

    # Compute gap fraction and concentration per session
    for session_id, loc_s in loc_valid_sorted.groupby("SESSION_ID"):
        alarm_s = alarms[alarms["SESSION_ID"] == session_id]

        gap_val = gap_fraction_fast(loc_s, alarm_s)
        cov_val = concentration_fast(loc_s["LOGGED_AT"].values, window_minutes)

        gap_list.append((session_id, gap_val))
        concentration_list.append((session_id, cov_val))

    # Convert computed metrics into DataFrames
    gap_df = pd.DataFrame(
        gap_list,
        columns=["SESSION_ID", "large_gap_fraction"],
    )
    concentration_df = pd.DataFrame(
        concentration_list,
        columns=["SESSION_ID", "concentration_window"],
    )

    # Merge all session-level metrics
    metrics = density[["SESSION_ID", "density", "baseline_density"]]
    metrics = metrics.merge(gps_pct, on="SESSION_ID", how="left")
    metrics = metrics.merge(gap_df, on="SESSION_ID", how="left")
    metrics = metrics.merge(concentration_df, on="SESSION_ID", how="left")
    metrics = metrics.merge(
        loc_present[["SESSION_ID", "session_has_locations"]],
        on="SESSION_ID",
        how="left",
    )

    # Fill missing indicators
    metrics["session_has_locations"] = metrics["session_has_locations"].fillna("no")
    metrics["pct_valid_gps"] = metrics["pct_valid_gps"].fillna(0)

    # Apply scoring logic to each session
    scores = metrics.apply(
        score_with_reasons,
        axis=1,
        result_type="expand",
    )

    # Extract score and reasons
    metrics["location_score"] = scores[0]
    metrics["location_score_reasons"] = scores[1]

    # Attach session-level metrics back to all original events
    df_out = events.merge(metrics, on="SESSION_ID", how="left")

    return df_out
