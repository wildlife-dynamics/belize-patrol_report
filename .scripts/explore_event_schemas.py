"""
Belize / SWCMR - event schema + sample-record deep dive.

Follow-up to explore_patrols_events.py, which found:
  - Patrol.patrol_type (boat/foot/vehicle/bicycle_patrol) is NOT the report's
    "mandate" (Day Patrol, Night Patrol, Joint Patrol, ...) - that must live
    somewhere else.
  - 5 relevant event types exist: patrol_details, patrol_completion_log,
    recreational_vessels, commercial_fishing_vessels_inspections,
    fishing_gear_removed_from_pa. No standalone "fishers" or "joint patrol
    team" event type was found by keyword - need to check if those live
    nested inside one of the 5 above.
  - The report's exact window (Feb 2026) has 0 patrols/events on this
    account; a wide 12-month window has 88 patrols - use that instead.

This script pulls the full JSON schema + a handful of real, populated sample
records for each of the 5 event types, and lists ALL event types on the
account (unfiltered) in case something was missed by keyword search.

Run with:
  cd /Users/zak/Documents/w-dynamics/ICMBio-patrol_analysis/ecoscope-workflows-patrol-analysis-workflow
  pixi run --locked -e default python ../../belize-patrol_report/.scripts/explore_event_schemas.py
"""

import datetime
import json

from ecoscope.platform.connections import EarthRangerConnection

er = EarthRangerConnection.from_named_connection("belize").get_client()
print(f"Connected to {er.server}\n")

UNTIL = datetime.datetime(2026, 9, 22, tzinfo=datetime.timezone.utc)
SINCE = UNTIL - datetime.timedelta(days=365)

EVENT_TYPES = [
    "patrol_details",
    "patrol_completion_log",
    "recreational_vessels",
    "commercial_fishing_vessels_inspections",
    "fishing_gear_removed_from_pa",
]


def hr(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


hr("0. ALL event types on this account (unfiltered)")
et_df = er.get_event_types()
for _, row in et_df.iterrows():
    print(f"  {row.get('value'):<45} {row.get('display'):<40} category={row.get('category')}")

# ---------------------------------------------------------------------------
hr("1. JSON schema per event type (field names/titles/choices)")
with er._use_v2_api():
    for et in EVENT_TYPES:
        try:
            schema = er._get(f"activity/eventtypes/{et}/schema")
        except Exception as e:
            print(f"\n  {et}: schema fetch error: {e}")
            continue
        props = schema.get("json", {}).get("properties", {})
        print(f"\n  --- {et} ---")
        for name, prop in props.items():
            kind = prop.get("type")
            title = prop.get("title")
            items = prop.get("items")
            extra = ""
            if items:
                extra = f" items.type={items.get('type')} items.properties={list(items.get('properties', {}).keys())}"
            print(f"    {name:<35} type={kind:<10} title={title}{extra}")

# ---------------------------------------------------------------------------
hr(f"2. Real sample records per event type, window {SINCE.date()} to {UNTIL.date()}")
id_lookup = dict(zip(et_df["value"], et_df["id"]))
for et in EVENT_TYPES:
    et_id = id_lookup.get(et)
    if et_id is None:
        print(f"\n  {et}: not found in event type list")
        continue
    try:
        events = er.get_events(since=SINCE.isoformat(), until=UNTIL.isoformat(), event_type=[et_id], include_details=True, drop_null_geometry=False)
    except Exception as e:
        print(f"\n  {et}: get_events error: {e}")
        continue
    print(f"\n  --- {et}: {len(events)} events in window ---")
    if len(events):
        print(f"      columns: {list(events.columns)}")
        # show up to 2 real samples with non-null event_details
        shown = 0
        for eid, ev in events.iterrows():
            details = ev.get("event_details")
            if not (isinstance(details, dict) and details):
                continue
            print(f"\n      event {eid}  time={ev.get('time')}  patrols={ev.get('patrols')}")
            for dk, dv in details.items():
                print(f"          {dk}: {json.dumps(dv, default=str)[:200]}")
            shown += 1
            if shown >= 2:
                break
        if shown == 0:
            print("      (no events with non-empty event_details found in this window)")

print("\nDone.")
