import pandas as pd
import numpy as np


def assign_locations_to_alarms(df_alarms, df_locations, verbose=False):
    """
    Match each alarm event to the nearest location ping (by timestamp)
    within the same session.

    Approach:
    ---------
    For each alarm:
    - Find the nearest location timestamp before it (backward match)
    - Find the nearest location timestamp after it (forward match)
    - Choose the closer of the two

    This ensures robust matching even if location pings are sparse or irregular.

    Parameters
    ----------
    df_alarms : pd.DataFrame
        Alarm events. Must contain:
        - SESSION_ID
        - LOGGED_AT (timestamp)
        - EVENT_ID (used for alignment)

    df_locations : pd.DataFrame
        Location pings. Must contain:
        - SESSION_ID
        - LOGGED_AT (timestamp)
        - latitude
        - longitude

    Returns
    -------
    pd.DataFrame
        Original alarm dataframe with additional columns:
        - latitude : matched latitude
        - longitude : matched longitude
        - loc_time_delta_sec : time difference (seconds) to matched location

    Notes
    -----
    - Matching is restricted within the same SESSION_ID
    - Uses pandas.merge_asof for efficient nearest-neighbor joins
    - Time delta is computed in seconds
    """

    # 1. Prepare location data
    locs = df_locations[['SESSION_ID', 'LOGGED_AT', 'latitude', 'longitude']].copy()

    # Drop rows with missing critical fields
    locs = locs.dropna(subset=['SESSION_ID', 'LOGGED_AT', 'latitude', 'longitude'])

    # Convert timestamps to int64 for fast numeric comparison
    locs['_t_loc'] = locs['LOGGED_AT'].astype('int64')

    # Required for merge_asof (must be sorted)
    locs = locs.sort_values('_t_loc').reset_index(drop=True)

    # 2. Prepare alarm data
    alarms = df_alarms.copy()
    alarms = alarms.dropna(subset=['SESSION_ID', 'LOGGED_AT'])

    alarms['_t'] = alarms['LOGGED_AT'].astype('int64')
    alarms = alarms.sort_values('_t').reset_index(drop=True)

    # 3. Handle edge cases
    if alarms.empty:
        # No alarms -> return empty structure with expected columns
        alarms['latitude'] = pd.Series(dtype='float64')
        alarms['longitude'] = pd.Series(dtype='float64')
        alarms['loc_time_delta_sec'] = pd.Series(dtype='float64')

        if verbose:
            print("\nLocated: 0 (0.0%)")
            print("Unlocated: 0 (sessions with no location pings)")
        return alarms

    if locs.empty:
        # No location data -> all alarms unlocated
        alarms['latitude'] = np.nan
        alarms['longitude'] = np.nan
        alarms['loc_time_delta_sec'] = np.nan

        alarms = alarms.drop(columns=['_t'])

        if verbose:
            print(f"\nLocated: 0 (0.0%)")
            print(f"Unlocated: {len(alarms):,} (sessions with no location pings)")
        return alarms.reset_index(drop=True)

    # 4. Prepare keys for merge
    alarm_keys = alarms[['EVENT_ID', 'SESSION_ID', '_t']]

    # 5. Find nearest location (backward and forward)
    # Backward: nearest location BEFORE alarm
    bwd = pd.merge_asof(
        alarm_keys,
        locs[['SESSION_ID', '_t_loc', 'latitude', 'longitude']],
        left_on='_t',
        right_on='_t_loc',
        by='SESSION_ID',
        direction='backward'
    )

    # Forward: nearest location AFTER alarm
    fwd = pd.merge_asof(
        alarm_keys,
        locs[['SESSION_ID', '_t_loc', 'latitude', 'longitude']],
        left_on='_t',
        right_on='_t_loc',
        by='SESSION_ID',
        direction='forward'
    )

    # 6. Compare distances and choose closest match
    t = alarms['_t']

    delta_bwd = (t - bwd['_t_loc']).abs()
    delta_fwd = (fwd['_t_loc'] - t).abs()

    # Handle missing matches using large sentinel value
    max_int = np.iinfo('int64').max
    use_bwd = delta_bwd.fillna(max_int) <= delta_fwd.fillna(max_int)

    # Select best match
    alarms['latitude'] = np.where(use_bwd, bwd['latitude'], fwd['latitude'])
    alarms['longitude'] = np.where(use_bwd, bwd['longitude'], fwd['longitude'])

    # Convert nanoseconds -> seconds
    alarms['loc_time_delta_sec'] = np.where(use_bwd, delta_bwd, delta_fwd) / 1e9

    # Cleanup
    alarms = alarms.drop(columns=['_t'])

    # 7. Summary stats (debugging / sanity check)
    located = alarms['latitude'].notna().sum()
    unlocated = alarms['latitude'].isna().sum()
    pct_located = 100 * located / len(alarms) if len(alarms) > 0 else 0

    if verbose:
        print(f"\nLocated: {located:,} ({pct_located:.1f}%)")
        print(f"Unlocated: {unlocated:,} (sessions with no location pings)")

    return alarms.reset_index(drop=True)
