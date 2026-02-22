import pandas as pd
import base64
from datetime import datetime

# Import your protobuf classes
from ctl.iox import (
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

EVENT_TYPE_TO_PROTO = {
    # Alarm-related
    "ALARM": alarm_pb2.AlarmRecord,
    "WARNING": alarm_pb2.AlarmRecord,
    "NOTIFICATION": alarm_pb2.AlarmRecord,

    # Battery
    "BATTERY": battery_pb2.BatteryRecord,
    "BATTERY_INFO": tag_pb2.BatteryPayload,

    # Location
    "LOCATION": location_pb2.LocationRecord,

    # Calibration / config
    "CALIBRATION": cal_record_pb2.CalRecord,

    # Cloud / connectivity
    "CLOUD_RESPONSE": inst_cloud_response_pb2.CloudResponse,
    "CONNECTIVITY": connectivity_pb2.ConnectivityMsg,

    # Tag / CICO
    "CICO": cico_pb2.TagRecord,

    # Instrument state
    "MODE": inst_mode_pb2.InstrumentModeRecord,

    # Sensor readings
    "READINGS": readings_pb2.ReadingsRecord,

    # Legacy / unsupported
    "GENERIC": None,
    "GRID_ACTION": None,
}


def decode_events_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes a dataframe with columns:
        - META_ENCODED_PROTO
        - EVENT_TYPE
        - LOGGED_AT
        - SESSION_ID

    Returns dataframe with additional columns:
        - decoded_message
        - latitude
        - longitude
        - valid_gps
    """

    df = df.copy()

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
            print(f"Failed to decode event_type={event_type}: {e}")
            return None

    # Decode protobufs
    df["decoded_message"] = df.apply(
        lambda row: decode_by_event_type(
            row["META_ENCODED_PROTO"],
            row["EVENT_TYPE"]
        ),
        axis=1
    )

    # Initialize new columns
    df["latitude"] = None
    df["longitude"] = None
    df["valid_gps"] = False

    # LOCATION-only processing
    df_location = df[df["EVENT_TYPE"] == "LOCATION"].copy()

    def extract_lat_lon(msg):
        lat = lon = None
        if isinstance(msg, str):
            for line in msg.splitlines():
                if line.strip().startswith("latitude:"):
                    try:
                        lat = int(line.split(":")[1].strip())
                    except:
                        lat = None
                elif line.strip().startswith("longitude:"):
                    try:
                        lon = int(line.split(":")[1].strip())
                    except:
                        lon = None
        return pd.Series([lat, lon])

    df_location["decoded_message"] = df_location["decoded_message"].astype(str)

    print(datetime.now(), "Starting lat/lon extraction...")

    df_location[["latitude", "longitude"]] = (
        df_location["decoded_message"]
        .apply(extract_lat_lon)
    )

    df_location["latitude"] = df_location["latitude"].astype(float) / 1e7
    df_location["longitude"] = df_location["longitude"].astype(float) / 1e7

    print(datetime.now(), "Completed lat/lon extraction.")

    df_location["valid_gps"] = (
        df_location["latitude"].between(-90, 90) &
        df_location["longitude"].between(-180, 180)
    )

    # Write results back to original df
    df.update(df_location[["latitude", "longitude", "valid_gps"]])

    return df