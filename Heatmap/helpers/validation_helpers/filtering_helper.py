import pandas as pd


def filter_correct_modes(events):
    """
    Filter events to the valid operating window within each session.

    For each session:
    - Identify the first occurrence of NORMAL operating mode as the start.
    - Identify the first occurrence of an end mode (CHARGING or OFF)
      that occurs after the start.
    - Keep only events that fall within this [start_time, end_time] window.

    Sessions that do not have both a valid start and end are removed.

    Parameters
    ----------
    events : pandas.DataFrame
        Input event data containing SESSION_ID, LOGGED_AT, and META_MODE.

    Returns
    -------
    pandas.DataFrame
        Filtered events restricted to valid operating windows per session.
        Returns an empty DataFrame if no valid sessions exist.
    """

    # Work on a copy and ensure timestamps are datetime
    df = events.copy()
    df["LOGGED_AT"] = pd.to_datetime(df["LOGGED_AT"])

    # Sort events within each session chronologically
    df = df.sort_values(["SESSION_ID", "LOGGED_AT"]).copy()

    normal = "OPERATING_MODE_NORMAL"
    end_modes = {
        "OPERATING_MODE_CHARGING",
        "OPERATING_MODE_OFF",
    }

    # Find the first NORMAL mode per session (start time)
    start_df = (
        df[df["META_MODE"] == normal]
        .groupby("SESSION_ID", as_index=False)["LOGGED_AT"]
        .min()
        .rename(columns={"LOGGED_AT": "start_time"})
    )

    # If no sessions have a valid start, return empty
    if start_df.empty:
        return df.iloc[0:0].copy()

    # Find candidate end events occurring after the start time
    end_candidates = df.merge(start_df, on="SESSION_ID", how="inner")
    end_candidates = end_candidates[
        (end_candidates["META_MODE"].isin(end_modes))
        & (end_candidates["LOGGED_AT"] > end_candidates["start_time"])
    ]

    # Select the earliest valid end time per session
    end_df = (
        end_candidates.groupby("SESSION_ID", as_index=False)["LOGGED_AT"]
        .min()
        .rename(columns={"LOGGED_AT": "end_time"})
    )

    # If no sessions have a valid end, return empty
    if end_df.empty:
        return df.iloc[0:0].copy()

    # Combine start and end times into valid windows
    windows = start_df.merge(end_df, on="SESSION_ID", how="inner")

    # Attach window bounds to original data
    df = df.merge(windows, on="SESSION_ID", how="inner")

    # Keep only events within the valid operating window
    result = df[
        (df["LOGGED_AT"] >= df["start_time"])
        & (df["LOGGED_AT"] <= df["end_time"])
    ].copy()

    # Return sorted result with clean indexing
    return result.sort_values(["SESSION_ID", "LOGGED_AT"]).reset_index(drop=True)

def filter_target_alarm_sessions(events):
    """
    Filter events to sessions containing at least one target alarm and
    remove non-target alarm events.

    The function:
    - Identifies sessions that contain at least one alarm of interest.
    - Removes alarm rows that are not part of the target alarm list.

    Parameters
    ----------
    events : pandas.DataFrame
        Input event data containing SESSION_ID, EVENT_TYPE, and META_ALARM.

    Returns
    -------
    pandas.DataFrame
        Filtered events containing only sessions with target alarms and
        only target alarm rows (plus all non-alarm events).
    """

    alarm_types = [
        "ALARM_GAS_EXPOSURE",
        "ALARM_GAS_DEFICIENCY",
        "ALARM_GAS_STEL",
        "ALARM_GAS_TWA",
        "ALARM_GAS_OVERRANGE",
        "ALARM_GAS_UNDERRANGE",
        "ALARM_WORKER_EMERGENCY",
        "ALARM_NOMOTION",
        "ALARM_NOMOTION_NORESPONSE",
        "ALARM_REMOTE_EVACUATION",
        "ALARM_CHECKIN_NORESPONSE",
    ]

    # Identify sessions that contain at least one target alarm
    target_sessions = events.loc[
        (events["EVENT_TYPE"] == "ALARM")
        & (events["META_ALARM"].isin(alarm_types)),
        "SESSION_ID",
    ].drop_duplicates()

    # Keep only events from those sessions
    filtered = events[
        events["SESSION_ID"].isin(target_sessions)
    ].copy()

    # Remove non-target alarm rows, keep all non-alarm events
    filtered = filtered[
        (filtered["EVENT_TYPE"] != "ALARM")
        | (
            (filtered["EVENT_TYPE"] == "ALARM")
            & (filtered["META_ALARM"].isin(alarm_types))
        )
    ]

    return filtered