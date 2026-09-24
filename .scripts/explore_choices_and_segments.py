"""
Belize / SWCMR - field choices + full patrol_segments structure.

Follow-up to explore_event_schemas.py. Two remaining unknowns before the PRD
can be finalized:
  1. patrol_details.patrol_mandate is a plain "string" in the schema dump -
     need its actual choice list to confirm it matches the report's "Patrols
     by Mandate" categories (Day Patrol, Night Patrol, Joint Patrol, ...).
  2. recreational_vessels.type_of_activities choices - the report splits
     "Recreational Fishing Vessels" vs "Recreational Tourism Vessels" as two
     tables, but there's only ONE recreational_vessels event type here - need
     to see if activity choices (e.g. Snorkelling/Diving vs Fishing) are how
     that split is made.
  3. Full (untruncated) patrol_segments on a real patrol - explore_patrols_
     events.py showed patrol has NO top-level distance/time/nights columns;
     need to confirm those really aren't on patrol_segments either (meaning
     they must be computed from patrol observations/trajectories, same as
     every other ecoscope patrol workflow in this org).

Run with:
  cd /Users/zak/Documents/w-dynamics/ICMBio-patrol_analysis/ecoscope-workflows-patrol-analysis-workflow
  pixi run --locked -e default python ../../belize-patrol_report/.scripts/explore_choices_and_segments.py
"""

import datetime
import json

from ecoscope.platform.connections import EarthRangerConnection

er = EarthRangerConnection.from_named_connection("belize").get_client()
print(f"Connected to {er.server}\n")

UNTIL = datetime.datetime(2026, 9, 22, tzinfo=datetime.timezone.utc)
SINCE = UNTIL - datetime.timedelta(days=365)


def hr(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


hr("1. Choice fields: patrol_details.patrol_mandate")
try:
    choices = er.get_choices_from_v2_event_type("patrol_details", "patrol_mandate")
    print(json.dumps(choices, indent=2, default=str))
except Exception as e:
    print(f"  error: {e}")

hr("2. Choice fields: recreational_vessels.type_of_activities")
try:
    choices = er.get_choices_from_v2_event_type("recreational_vessels", "type_of_activities")
    print(json.dumps(choices, indent=2, default=str))
except Exception as e:
    print(f"  error: {e}")

hr("3. Choice fields: commercial_fishing_vessels_inspections.type_of_inspection / vessel_type")
for field in ["type_of_inspection", "vessel_type", "type_of_gear"]:
    try:
        choices = er.get_choices_from_v2_event_type("commercial_fishing_vessels_inspections", field)
        print(f"\n  {field}:")
        print(json.dumps(choices, indent=2, default=str))
    except Exception as e:
        print(f"  {field}: error: {e}")

# ---------------------------------------------------------------------------
hr("4. Full patrol_segments structure on real patrols (any distance/time_range hiding here?)")
patrols = er.get_patrols(since=SINCE.isoformat(), until=UNTIL.isoformat())
non_empty = patrols[patrols["patrol_segments"].apply(lambda s: isinstance(s, list) and len(s) > 0)]
print(f"  patrols with segments: {len(non_empty)} / {len(patrols)}\n")
if len(non_empty):
    seg = non_empty.iloc[0]["patrol_segments"][0]
    print("  Full first segment (all keys):")
    for k, v in seg.items():
        print(f"    {k}: {json.dumps(v, default=str)[:300]}")

# ---------------------------------------------------------------------------
hr("5. Patrol observations (GPS track) availability for a real patrol - to confirm "
   "distance/duration must be computed from trajectories, not a raw field")
if len(non_empty):
    patrol_id = non_empty.iloc[0]["id"]
    try:
        obs = er.get_patrol_observations_with_patrol_filter(patrol_ids=[patrol_id], include_source_details=False)
        print(f"  observations for patrol {patrol_id}: {len(obs)}")
        if len(obs):
            print(f"  columns: {list(obs.columns)}")
    except Exception as e:
        print(f"  get_patrol_observations_with_patrol_filter error: {e}")

print("\nDone.")
