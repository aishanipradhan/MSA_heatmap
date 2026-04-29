import base64
from datetime import datetime
import pandas as pd

# Protobuf imports
from helpers.Protobuffer_Deserialization.ctl.iox import (
    location_pb2,
    readings_pb2,
    alarm_pb2,
    pf_instrument_config_pb2,
    cal_record_pb2,
    inst_mode_pb2,
    inst_debug_pb2,
    inst_cloud_response_pb2,
    cico_pb2,
    battery_pb2,
    sensor_states_record_pb2,
    tag_pb2,
    connectivity_pb2
)


# Mapping: event_type → proto class
EVENT_TYPE_TO_PROTO = {
    "ALARM": alarm_pb2.AlarmRecord,
    "WARNING": alarm_pb2.AlarmRecord,
    "NOTIFICATION": alarm_pb2.AlarmRecord,

    "BATTERY": battery_pb2.BatteryRecord,
    "BATTERY_INFO": tag_pb2.BatteryPayload,

    "LOCATION": location_pb2.LocationRecord,
    "CALIBRATION": cal_record_pb2.CalRecord,

    "CLOUD_RESPONSE": inst_cloud_response_pb2.CloudResponse,
    "CONNECTIVITY": connectivity_pb2.ConnectivityMsg,

    "CICO": cico_pb2.TagRecord,
    "MODE": inst_mode_pb2.InstrumentModeRecord,

    "READINGS": readings_pb2.ReadingsRecord,

    # Unsupported / legacy
    "GENERIC": None,
    "GRID_ACTION": None,
}


# 1. Decode protobuf
def decode_by_event_type(encoded_proto, event_type):
    if pd.isna(encoded_proto) or not event_type:
        return None

    proto_cls = EVENT_TYPE_TO_PROTO.get(event_type)

    if proto_cls is None:
        return None

    try:
        if isinstance(encoded_proto, (bytes, bytearray)):
            raw = encoded_proto
        else:
            raw = base64.b64decode(encoded_proto)

        msg = proto_cls()
        msg.ParseFromString(raw)
        return msg

    except Exception as e:
        print(f"[Decode Error] event_type={event_type}: {e}")
        return None


# 2. Decode entire dataframe 
def decode_events(df):
    df = df.copy()

    print(datetime.now(), "Starting decoding...")

    df["decoded_message"] = [
        decode_by_event_type(ep, et)
        for ep, et in zip(df["META_ENCODED_PROTO"], df["EVENT_TYPE"])
    ]

    df["decoded_type"] = [
        msg.DESCRIPTOR.full_name if msg else None
        for msg in df["decoded_message"]
    ]

    print(datetime.now(), "Completed decoding.")

    return df


# 3. Extract lat/lon
def extract_lat_lon_from_message(msg):
    lat = lon = None

    if isinstance(msg, str):
        for line in msg.splitlines():
            line = line.strip()

            if line.startswith("latitude:"):
                try:
                    lat = int(line.split(":")[1].strip())
                except:
                    lat = None

            elif line.startswith("longitude:"):
                try:
                    lon = int(line.split(":")[1].strip())
                except:
                    lon = None

    return lat, lon


# 4. Add location features
def add_location_columns(df):
    df = df.copy()

    print(datetime.now(), "Starting lat/lon extraction...")

    location_df = df[df["EVENT_TYPE"] == "LOCATION"].copy()

    lat_lon = [
        extract_lat_lon_from_message(str(msg))
        for msg in location_df["decoded_message"]
    ]

    location_df[["latitude", "longitude"]] = pd.DataFrame(
        lat_lon, index=location_df.index
    )

    # Scale
    location_df["latitude"] = location_df["latitude"].astype(float) / 1e7
    location_df["longitude"] = location_df["longitude"].astype(float) / 1e7

    # Validity flag
    location_df["gps_valid"] = (
        location_df["latitude"].between(-90, 90) &
        location_df["longitude"].between(-180, 180)
    )

    print(datetime.now(), "Completed lat/lon extraction.")

    # lat, lon and gps_valid will be NaN for non-location events
    return df.merge(
        location_df[["SESSION_ID", "EVENT_ID", "latitude", "longitude", "gps_valid"]],
        on=["SESSION_ID", "EVENT_ID"],
        how="left"
    )


# 5. Full pipeline
def deserialize_events(df):
    """
    Full pipeline:
    - Deserialize protobufs
    - Extract location features
    """
    df = decode_events(df)
    df = add_location_columns(df)
    return df