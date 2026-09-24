"""
Belize / South Water Caye Marine Reserve (SWCMR) - data exploration

Confirms against the "belize" EarthRanger instance what's actually available
before scaffolding a workflow, checked against the fields used in the
partner's existing report (SWCMR_Report_000054.pdf, titled "SMART Monthly
Report" on the PDF itself - this is a replication exercise off data already
in EarthRanger, not a SMART Connect integration):
  - Patrol Effort Summary (# patrols, distance, nights, patrol hours, fuel)
  - Staff Effort (per-officer patrols/nights/distance/hours)
  - Patrols by Mandate (patrol type) + Type of Vessels Inspected charts
  - Joint Patrol Team table
  - Vessels Documented (recreational fishing / commercial fishing /
    subsistence fishing / tourism vessel counts)
  - Recreational Fishing / Tourism Vessels Particulars tables
  - Commercial Fishing Vessels Encountered table
  - Fishers Documented table
  - Map of Activities Documented (waypoints by category + AOI layers)

Per the user: each patrol carries patrol_details, and a "patrol completion"
log event (a per-patrol wrap-up event attached directly in ER) carries the
encounter records (vessels/fishers/joint-team) as event_details on events
attached to the patrol. This script does NOT assume that shape - it dumps
real schema and sample records so the PRD's field mapping is verified, not
guessed.

Run with (uses ICMBio-patrol_analysis's compiled env, which already has
ecoscope + EarthRangerConnection - this project doesn't have its own env
yet):
  cd /Users/zak/Documents/w-dynamics/ICMBio-patrol_analysis/ecoscope-workflows-patrol-analysis-workflow
  pixi run --locked -e default python ../../belize-patrol_report/.scripts/explore_patrols_events.py
"""

import datetime
import json
from collections import Counter

from ecoscope.platform.connections import EarthRangerConnection

er = EarthRangerConnection.from_named_connection("belize").get_client()
print(f"Connected to {er.server}\n")

# Report's own period (SWCMR_Report_000054.pdf): Feb 1-28, 2026
REPORT_SINCE = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)
REPORT_UNTIL = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc)

# Wider sanity-check window
WIDE_UNTIL = datetime.datetime(2026, 9, 22, tzinfo=datetime.timezone.utc)
WIDE_SINCE = WIDE_UNTIL - datetime.timedelta(days=365)


def hr(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def dump_sample(record: dict, limit=250):
    for k, v in record.items():
        if v is None or v == [] or v == {} or v == "":
            continue
        print(f"    {k}: {json.dumps(v, default=str)[:limit]}")


# ---------------------------------------------------------------------------
hr("1. Patrol types (mandates) - report's 'Patrols by Mandate' chart expects:"
   "\n   Day Patrol, Night Patrol, Joint Patrol, Logistics Support, Monitoring,"
   "\n   Shift Change, Spags Patrol, Intelligence Verification")
pt_df = er.get_patrol_types()
print(f"columns: {list(pt_df.columns)}\n")
expected_mandates = [
    "Day Patrol", "Night Patrol", "Joint Patrol", "Logistics Support",
    "Monitoring", "Shift Change", "Spags Patrol", "Intelligence Verification",
]
display_values = set(pt_df["display"]) if "display" in pt_df.columns else set()
for m in expected_mandates:
    print(f"  {'OK  ' if m in display_values else 'CHECK'} {m}")
print("\nAll patrol types actually on this account:")
for _, row in pt_df.iterrows():
    print(f"  {row.get('value'):<25} {row.get('display')}")

# ---------------------------------------------------------------------------
hr("2. Event types - looking for vessel / fisher / joint-team / patrol-completion records")
et_df = er.get_event_types()
print(f"columns: {list(et_df.columns)}\n")
KEYWORDS = ["vessel", "fisher", "fishing", "patrol", "joint", "boat", "inspect", "tour", "smart"]
for _, row in et_df.iterrows():
    val = str(row.get("value", "")).lower()
    disp = str(row.get("display", "")).lower()
    if any(k in val or k in disp for k in KEYWORDS):
        print(f"  {row.get('value'):<40} {row.get('display')}")

# ---------------------------------------------------------------------------
hr(f"3. Patrol volume - report window {REPORT_SINCE.date()} to {REPORT_UNTIL.date()} "
   f"(report says: 27 patrols)")
try:
    patrols_report_window = er.get_patrols(since=REPORT_SINCE.isoformat(), until=REPORT_UNTIL.isoformat())
    print(f"  patrols found: {len(patrols_report_window)}")
except Exception as e:
    print(f"  get_patrols error: {e}")
    patrols_report_window = None

hr(f"3b. Patrol volume - wide sanity window {WIDE_SINCE.date()} to {WIDE_UNTIL.date()}")
try:
    patrols_wide = er.get_patrols(since=WIDE_SINCE.isoformat(), until=WIDE_UNTIL.isoformat())
    print(f"  patrols found: {len(patrols_wide)}")
except Exception as e:
    print(f"  get_patrols error: {e}")
    patrols_wide = None

patrols = patrols_report_window if patrols_report_window is not None and len(patrols_report_window) else patrols_wide

# ---------------------------------------------------------------------------
hr("4. Patrol columns + sample patrol record (fields the PRD's stat cards / "
   "Staff Effort table need: leader/officer, distance, nights, hours, fuel, patrol type)")
if patrols is not None and len(patrols):
    print(f"columns: {list(patrols.columns)}\n")
    print("Sample patrol record (first result), non-null fields:")
    dump_sample(patrols.iloc[0].to_dict())

    PRD_PATROL_FIELDS = {
        "Patrol type / mandate": ["patrol_type", "patrol_type_display"],
        "Officer / leader": ["patrol_leader", "leader", "patrol_segments"],
        "Distance covered": ["distance", "distance_covered"],
        "Start/end time": ["start_time", "end_time", "time_range"],
        "Fuel used": ["fuel_used", "fuel"],
        "Nights": ["nights", "number_of_nights"],
    }
    print("\nField-mapping check:")
    for label, candidates in PRD_PATROL_FIELDS.items():
        found = [c for c in candidates if c in patrols.columns]
        print(f"  {'OK  ' if found else 'CHECK'} {label:<28} matched: {found if found else candidates}")
else:
    print("  no patrols returned in either window - cannot inspect columns")

# ---------------------------------------------------------------------------
hr("5. Patrol events - get_patrol_events (lightweight refs) for the report window")
try:
    patrol_events = er.get_patrol_events(
        since=REPORT_SINCE.isoformat(), until=REPORT_UNTIL.isoformat(),
        patrol_type_value=None, event_type=None, status=None,
        drop_null_geometry=False, sub_page_size=None, patrols_overlap_daterange=True,
    )
    print(f"  total patrol-linked events found: {len(patrol_events)}")
    print(f"  columns: {list(patrol_events.columns)}")
except Exception as e:
    print(f"  get_patrol_events error: {e}")
    patrol_events = None

# ---------------------------------------------------------------------------
hr("6. Full event details for those event IDs, and event_details schema per type "
   "(this is where vessel/fisher/joint-team encounter records should live)")
if patrol_events is not None and len(patrol_events):
    sample_ids = set(patrol_events["id"].dropna().tolist()) if "id" in patrol_events.columns else set(
        patrol_events.index.tolist()
    )
    detailed = er.get_events(
        since=REPORT_SINCE.isoformat(), until=REPORT_UNTIL.isoformat(),
        include_details=True, drop_null_geometry=False,
    )
    print(f"  detailed events fetched in window: {len(detailed)}")
    matched = detailed[detailed.index.to_series().isin(sample_ids)] if len(detailed) else detailed
    print(f"  matched to patrol-linked event IDs: {len(matched)}\n")

    by_type = Counter(matched["event_type"]) if "event_type" in matched.columns else Counter()
    print("  breakdown by event_type (id):")
    for et, count in by_type.most_common():
        print(f"    {et}: {count}")

    print("\n  Sample event_details per event_type (first example of each):")
    seen_types = set()
    for eid, ev in matched.iterrows():
        et = ev.get("event_type")
        if et in seen_types:
            continue
        seen_types.add(et)
        display = et_df.loc[et_df["id"] == et, "display"].values
        display = display[0] if len(display) else et
        print(f"\n  --- event_type={et} ({display}) ---")
        details = ev.get("event_details")
        if isinstance(details, dict) and details:
            for dk, dv in details.items():
                print(f"      {dk}: {json.dumps(dv, default=str)[:200]}")
        else:
            print("      (event_details empty on this record)")
else:
    print("  no patrol events to inspect")

# ---------------------------------------------------------------------------
hr("7. All events in report window regardless of patrol link (in case vessel/fisher "
   "records are NOT attached via patrol_events but standalone, e.g. under a "
   "'patrol completion' parent event with nested log entries)")
try:
    all_events = er.get_events(
        since=REPORT_SINCE.isoformat(), until=REPORT_UNTIL.isoformat(),
        include_details=True, drop_null_geometry=False,
    )
    print(f"  total events in window: {len(all_events)}")
    if "event_type" in all_events.columns:
        by_type_all = Counter(all_events["event_type"])
        print("  breakdown by event_type (id):")
        for et, count in by_type_all.most_common():
            display = et_df.loc[et_df["id"] == et, "display"].values
            display = display[0] if len(display) else et
            print(f"    {et} ({display}): {count}")
except Exception as e:
    print(f"  get_events error: {e}")

print("\nDone.")
