"""AppMetrica Logs API tables and their fields.

Field lists follow the Logs API reference
(https://appmetrica.yandex.com/docs/en/mobile-api/logs/endpoints). The docs lag
the API: when a field is rejected, sync drops it from the request, remembers it
in `source_fields.rejected` and keeps going - an unknown field degrades to a
NULL column instead of a failed sync. Adding a field here is safe: the next
sync adds the column to an existing database.
"""

from __future__ import annotations

from .base import INTEGER, REAL, Table

# uint64 identifiers (appmetrica_device_id, session_id, ...) are kept as TEXT on
# purpose: SQLite INTEGER is signed 64-bit and overflows above 2^63.
FIELD_TYPES: dict[str, str] = {
    "event_timestamp": INTEGER,
    "event_receive_timestamp": INTEGER,
    "session_start_timestamp": INTEGER,
    "session_start_receive_timestamp": INTEGER,
    "install_timestamp": INTEGER,
    "install_receive_timestamp": INTEGER,
    "click_timestamp": INTEGER,
    "crash_timestamp": INTEGER,
    "crash_receive_timestamp": INTEGER,
    "error_timestamp": INTEGER,
    "error_receive_timestamp": INTEGER,
    "ad_revenue_timestamp": INTEGER,
    "ad_revenue_receive_timestamp": INTEGER,
    "app_build_number": INTEGER,
    "appmetrica_sdk_version": INTEGER,
    "revenue_quantity": INTEGER,
    "revenue_price": REAL,
    "ad_revenue": REAL,
}

_DEVICE = [
    "appmetrica_device_id",
    "installation_id",
    "profile_id",
    "os_name",
    "os_version",
    "device_manufacturer",
    "device_model",
    "original_device_model",
    "device_type",
    "device_locale",
    "connection_type",
    "country_iso_code",
    "city",
]

# Advertising and network identifiers: requested only with --with-device-ids,
# so the local database stays free of personal data by default.
_DEVICE_PII = [
    "google_aid",
    "ios_ifa",
    "ios_ifv",
    "windows_aid",
    "android_id",
    "device_ipv6",
    "operator_name",
    "mcc",
    "mnc",
]

_APP = [
    "app_version_name",
    "app_build_number",
    "app_package_name",
]

# Attribution lives in installations: publisher_name / tracker_name tell paid
# from organic (see v_installs in schema_core.sql).
_ATTRIBUTION = [
    "publisher_id",
    "publisher_name",
    "tracking_id",
    "tracker_name",
]


def _table(name: str, date_field: str, own: list[str], *, default: bool = False,
           json_field: str | None = None, attribution: bool = False) -> Table:
    fields = _DEVICE + _APP + (_ATTRIBUTION if attribution else []) + own
    return Table(name=name, fields=fields, date_field=date_field,
                 json_field=json_field, default=default,
                 pii_fields=list(_DEVICE_PII), types=FIELD_TYPES,
                 device_field="appmetrica_device_id")


TABLES: list[Table] = [
    _table("events", "event_datetime", [
        "session_id",
        "event_name",
        "event_json",
        "event_datetime",
        "event_timestamp",
        "event_receive_datetime",
        "event_receive_timestamp",
    ], default=True, json_field="event_json"),
    _table("sessions_starts", "session_start_datetime", [
        "session_id",
        "session_start_datetime",
        "session_start_timestamp",
        "session_start_receive_datetime",
        "session_start_receive_timestamp",
    ], default=True),
    _table("installations", "install_datetime", [
        "match_type",
        "is_reinstallation",
        "click_datetime",
        "click_timestamp",
        "install_datetime",
        "install_timestamp",
        "install_receive_datetime",
        "install_receive_timestamp",
    ], default=True, attribution=True),
    _table("crashes", "crash_datetime", [
        "crash",
        "crash_id",
        "crash_group_id",
        "crash_datetime",
        "crash_timestamp",
        "crash_receive_datetime",
        "crash_receive_timestamp",
    ]),
    _table("errors", "error_datetime", [
        "error",
        "error_id",
        "error_name",
        "error_datetime",
        "error_timestamp",
        "error_receive_datetime",
        "error_receive_timestamp",
    ]),
    _table("revenue_events", "event_datetime", [
        "session_id",
        "event_name",
        "event_datetime",
        "event_timestamp",
        "event_receive_datetime",
        "event_receive_timestamp",
        "revenue_quantity",
        "revenue_price",
        "revenue_currency",
        "revenue_product_id",
        "revenue_order_id",
        "revenue_order_id_source",
        "is_revenue_verified",
        "appmetrica_sdk_version",
    ]),
    _table("ad_revenue_events", "ad_revenue_datetime", [
        "session_id",
        "ad_revenue_datetime",
        "ad_revenue_timestamp",
        "ad_revenue_receive_datetime",
        "ad_revenue_receive_timestamp",
        "ad_revenue",
        "ad_revenue_currency",
        "ad_revenue_type",
        "ad_revenue_data_source",
        "ad_revenue_network",
        "ad_revenue_placement_id",
        "ad_revenue_placement_name",
        "ad_revenue_unit_id",
        "ad_revenue_unit_name",
        "ad_revenue_precision",
        "ad_revenue_payload",
        "appmetrica_sdk_version",
    ]),
]
