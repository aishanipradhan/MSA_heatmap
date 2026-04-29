import pandas as pd


# For all sessions, general EDA
def session_length(events):
    """
    Calculate the active duration of each session, defined as the window
    between the first NORMAL mode event and the next OFF or CHARGING event
    (or the last event in the session if neither occurs).

    Sessions without any MODE events, or without a NORMAL mode, are skipped
    entirely — they can't be meaningfully measured.

    Args:
        events: Events DataFrame. Needs SESSION_ID, LOGGED_AT, EVENT_TYPE,
                and META_MODE.

    Returns:
        DataFrame with one row per valid session and columns:
            SESSION_ID   – session identifier
            window_start – timestamp of first NORMAL mode event
            window_end   – timestamp of OFF/CHARGING event, or last event
            duration_hr  – window length in hours
            has_normal   – always True (falsy sessions are excluded)
    """
    events = events.copy()
    events["LOGGED_AT"] = pd.to_datetime(events["LOGGED_AT"])

    normal = "OPERATING_MODE_NORMAL"
    off = "OPERATING_MODE_OFF"
    charging = "OPERATING_MODE_CHARGING"
    end_modes = {off, charging}

    results = []

    for session_id, group in events.groupby("SESSION_ID"):
        group = group.sort_values("LOGGED_AT")

        mode_events = group[group["EVENT_TYPE"] == "MODE"]

        # Exclude sessions missing modes entirely
        if mode_events.empty:
            continue

        # Exclude sessions with no NORMAL mode
        if normal not in mode_events["META_MODE"].values:
            continue

        # Helper: first OFF or CHARGING after a given timestamp
        def first_end_mode(after_ts):
            candidates = mode_events[
                (mode_events["META_MODE"].isin(end_modes))
                & (mode_events["LOGGED_AT"] > after_ts)
            ]["LOGGED_AT"]

            return candidates.min() if not candidates.empty else None

        # Only consider session after first NORMAL mode
        window_start = mode_events.loc[
            mode_events["META_MODE"] == normal,
            "LOGGED_AT",
        ].min()

        end_ts = first_end_mode(after_ts=window_start)
        window_end = (
            end_ts if end_ts is not None else group["LOGGED_AT"].max()
        )

        duration = (
            window_end - window_start
        ).total_seconds() / 3600

        results.append(
            {
                "SESSION_ID": session_id,
                "window_start": window_start,
                "window_end": window_end,
                "duration_hr": duration,
                "has_normal": True,
            }
        )

    return pd.DataFrame(results)


# Specifically for sessions with alarms, to analyze whether they occur
# within the NORMAL -> OFF/CHARGING window or outside of it
def session_length_alarms(events):
    """
    Like session_length(), but restricted to sessions that have alarm events,
    and tagged by whether those alarms actually fall inside the active window.

    The active window is still NORMAL → OFF/CHARGING (or last event).
    Sessions without MODE events, without a NORMAL mode, or without any
    alarm events are skipped.

    Useful for separating "device alarmed while in use" from "alarm logged
    outside the expected operating window" — the latter often points to a
    data quality issue worth investigating.

    Args:
        events: Events DataFrame. Needs SESSION_ID, LOGGED_AT, EVENT_TYPE,
                META_MODE, and META_TYPE.

    Returns:
        DataFrame with one row per valid session and columns:
            SESSION_ID        – session identifier
            window_start      – timestamp of first NORMAL mode event
            window_end        – timestamp of OFF/CHARGING event, or last event
            duration_hr       – window length in hours
            has_normal        – always True
            alarms_in_window  – True if any alarm falls within the window
            case_type         – "NORMAL_WITH_ALARMS" or
                                "NORMAL_NO_ALARMS_IN_WINDOW"
            notes             – None if alarms are in-window, otherwise a
                                short explanation
    """
    events = events.copy()
    events["LOGGED_AT"] = pd.to_datetime(events["LOGGED_AT"])

    normal = "OPERATING_MODE_NORMAL"
    off = "OPERATING_MODE_OFF"
    charging = "OPERATING_MODE_CHARGING"
    end_modes = {off, charging}

    results = []

    for session_id, group in events.groupby("SESSION_ID"):
        group = group.sort_values("LOGGED_AT")

        mode_events = group[group["EVENT_TYPE"] == "MODE"]
        alarm_events = group[
            group["META_TYPE"] == "ALARM_TYPE_ALARM"
        ]

        # Exclude sessions missing modes or alarms entirely
        if mode_events.empty or alarm_events.empty:
            continue

        # Exclude sessions with no NORMAL mode
        if normal not in mode_events["META_MODE"].values:
            continue

        # Helper: first OFF or CHARGING after a given timestamp
        def first_end_mode(after_ts):
            candidates = mode_events[
                (mode_events["META_MODE"].isin(end_modes))
                & (mode_events["LOGGED_AT"] > after_ts)
            ]["LOGGED_AT"]

            return candidates.min() if not candidates.empty else None

        # Only consider session after first NORMAL mode
        window_start = mode_events.loc[
            mode_events["META_MODE"] == normal,
            "LOGGED_AT",
        ].min()

        end_ts = first_end_mode(after_ts=window_start)
        window_end = (
            end_ts if end_ts is not None else group["LOGGED_AT"].max()
        )

        alarms_in_window = alarm_events[
            (alarm_events["LOGGED_AT"] >= window_start)
            & (alarm_events["LOGGED_AT"] <= window_end)
        ]

        duration = (
            window_end - window_start
        ).total_seconds() / 3600

        has_alarm_in_window = not alarms_in_window.empty

        results.append(
            {
                "SESSION_ID": session_id,
                "window_start": window_start,
                "window_end": window_end,
                "duration_hr": duration,
                "has_normal": True,
                "alarms_in_window": has_alarm_in_window,
                "case_type": (
                    "NORMAL_WITH_ALARMS"
                    if has_alarm_in_window
                    else "NORMAL_NO_ALARMS_IN_WINDOW"
                ),
                "notes": (
                    None
                    if has_alarm_in_window
                    else (
                        "Alarms exist but fall outside "
                        "NORMAL->OFF/CHARGING window"
                    )
                ),
            }
        )

    return pd.DataFrame(results)
