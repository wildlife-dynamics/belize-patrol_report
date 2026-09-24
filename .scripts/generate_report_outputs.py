"""
Belize Fisheries Department - end-to-end output generation (proof that "all
outputs" from the PRD can actually be produced from real data, not just
schema-checked).

Pipeline, step by step:
  1. Connect to the `belize` EarthRanger account.
  2. Pull all patrols in the reporting window (optionally scoped to a single
     patrol via PATROL_SERIAL_NUMBER, for an "Individual Patrol Report").
  3. Get ALL events actually attached to those patrols directly off the
     `patrols` DataFrame's own patrol_segments[].events (patrol_events_gdf(),
     no extra API call) - then filter that down to just the event types the
     SOURCE PDF's own tables need (EVENT_TYPE_KEYS: patrol_details,
     patrol_completion_log, recreational_vessels,
     commercial_fishing_vessels_inspections), dropping anything else the
     account happens to log on a patrol (wildlife_observations, beach_traps,
     fishing_gear_removed_from_pa, cargo_or_other_types_of_vessesls - all
     real, but no section in the source report covers them). The embedded
     event refs don't carry event_details, so full field values are hydrated
     in bulk via `get_events(..., include_details=True)` afterward,
     restricted to just the already-identified event ids - not a second
     broad fetch.
  4. Resolve every code -> display-name mapping LIVE from the account, never
     hardcoded: patrol transport type (`er.get_patrol_types()`), patrol
     mandate (the account's own choices schema for `patrol_mandate`), event
     type (`er.get_event_types()`, already pulled in step 3). Also resolve a
     shared categorical color palette via
     `ecoscope.analysis.classifier.resolve_categorical_cmap_colors` on the
     "tab20b" colormap - the same default palette every ChartStyle-driven
     chart in this codebase uses (ecoscope.platform.tasks.config.set_chart) -
     so charts and the map share one consistent, non-arbitrary color scheme.
  5. Assemble one composite row per patrol (leader, transport type, mandate,
     completion-log fields, counts of attached vessel/gear events).
  6. Compute real distance/duration for a capped subset of patrols via
     Relocations -> Trajectory (the correct call is
     `er.get_patrol_observations(patrols_df=...)`, NOT
     `get_patrol_observations_with_patrol_filter` - the latter ignores a
     patrol_ids-style filter and silently pulls full subject history, which
     is what an earlier exploration script here caught).
  7. Build exactly the 8 tables the source PDF has (Patrol Effort Summary,
     Staff Effort, Vessels Documented, Recreational Fishing Vessels,
     Recreational Tourism Vessels, Commercial Fishing Vessels Encountered,
     Fishers Documented, plus a patrols-detail reference table that isn't in
     the PDF but is useful raw output) as real DataFrames from real records -
     no additions beyond what the source report actually has (Joint Patrol
     Team is also in the source PDF but has no matching event type on this
     account at all - see the PRD's open question #4).
  8. Write every table to CSV.
  9. Render the 2 non-redundant charts the source PDF has (Patrols by
     Mandate, and Type of Vessels Inspected - both bar charts) as standalone
     Plotly HTML, using the same ecoscope.plotting functions the production
     dashboard uses. The PDF's third chart, "Number of
     Patrols" (a single bar), is just the same number already in Patrol
     Effort Summary and is skipped as redundant.
  10. Render a map (patrol tracks + event waypoints) as standalone HTML using
     create_path_layer/create_scatterplot_layer/draw_map - the pydeck-backed
     map task every other patrol workflow in this org uses (see
     ICMBio-patrol_analysis/spec.yaml's "Patrol Coverage Map" task-group) -
     with two separate legends (Patrol Type, Event Type), each driven by a
     color column on its own layer's GeoDataFrame (LegendFromDataframe)
     rather than one fixed color per layer.
  11. Print a manifest of everything written.

Run with:
  cd /Users/zak/Documents/w-dynamics/ICMBio-patrol_analysis/ecoscope-workflows-patrol-analysis-workflow
  pixi run --locked -e default python ../../belize-patrol_report/.scripts/generate_report_outputs.py
"""

import datetime
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.geometry import shape

from ecoscope.analysis.classifier import resolve_categorical_cmap_colors
from ecoscope.platform.connections import EarthRangerConnection
from ecoscope.relocations import Relocations
from ecoscope.trajectory import Trajectory
from ecoscope.plotting import BarConfig, bar_chart
# draw_map (pydeck-backed), not draw_ecomap (lonboard-backed) - draw_map is the map
# task every other patrol workflow in this org actually uses (draw_ecomap has just
# one user, ops-dashboard); see ICMBio-patrol_analysis/spec.yaml's "Patrol Coverage
# Map" task-group for the exact pattern this mirrors: one path layer for tracks with
# its own "legend by patrol type", one scatterplot layer for events with its own
# legend, both driven by a color column on the dataframe (LegendFromDataframe) rather
# than a fixed list of colors per layer.
from ecoscope.platform.tasks.results._pydeck import (
    LegendFromDataframe,
    LegendStyle,
    PathLayerStyle,
    ScatterplotLayerStyle,
    create_path_layer,
    create_scatterplot_layer,
    draw_map,
)
from ecoscope.platform.tasks.results._map_utils import TileLayer

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OUT_DIR = Path(__file__).parent / "output"
TABLES_DIR = OUT_DIR / "tables"
CHARTS_DIR = OUT_DIR / "charts"
for d in (TABLES_DIR, CHARTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

UNTIL = datetime.datetime(2026, 9, 22, tzinfo=datetime.timezone.utc)
# Matches the source PDF's own report start date (SWCMR_Report_000054.pdf: Feb 1, 2026).
# NOTE: the account's earliest patrols are actually Dec 2025 (serials 1-5), then there's
# a real gap with nothing until late June 2026 - Feb 2026 itself has 0 patrols on this
# account, confirmed earlier in explore_patrols_events.py. Starting here anyway, per request,
# so this window matches what a partner running "since Feb 2026" would actually see.
SINCE = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)

# Set to a specific patrol's serial_number to scope the ENTIRE report to just that
# one patrol (the "Individual Patrol Report" case) - e.g. PATROL_SERIAL_NUMBER = 51.
# Leave as None for the normal full-period report. When set, every step below -
# events, tables, distance/trajectory, map - is scoped to that one patrol only.
PATROL_SERIAL_NUMBER: int | None = None

# Full trajectory computation (real GPS track -> distance) is per-patrol and
# costs one or more API calls each; capped here to keep this demo script
# fast. The real workflow will compute this for every patrol, in parallel,
# as a normal ecoscope-workflows DAG step (the "trajs" pattern used by every
# other patrol workflow in this org) - this cap is a demo-script concession,
# not a production design choice.
MAX_PATROLS_FOR_TRACKS = 15

# Exactly the event types the source PDF's tables need - see PRD "Multi-site scope"
# and open questions for fishing_gear_removed_from_pa / cargo_or_other_types_of_vessesls,
# which are real event types with real data on this account but have no matching
# section in the source report, so they're deliberately left out of scope here.
EVENT_TYPE_KEYS = [
    "patrol_details",
    "patrol_completion_log",
    "recreational_vessels",
    "commercial_fishing_vessels_inspections",
]

# Fixed display order for the vessel/activity categories this report builds (not
# a literal ER event type - "Recreational Fishing"/"Recreational Tourism" are both
# derived from the single `recreational_vessels` event type, split by activity).
# Order is fixed (not re-sorted by count) so a category's color never changes
# between runs - color follows identity, not rank.
CATEGORY_ORDER = [
    "Commercial Fishing",
    "Recreational Fishing",
    "Recreational Tourism",
]


def hr(n, title):
    print("\n" + "=" * 78)
    print(f"STEP {n}: {title}")
    print("=" * 78)


def write_csv(df: pd.DataFrame, name: str):
    path = TABLES_DIR / f"{name}.csv"
    df.to_csv(path, index=False)
    print(f"  wrote {path}  ({len(df)} rows)")
    return path


def patrol_events_gdf(patrols_df: pd.DataFrame) -> gpd.GeoDataFrame:
    """One row per event embedded in patrols_df's own patrol_segments[].events.

    No API call - this is data already sitting in patrols_df from the get_patrols()
    fetch. Scoping (e.g. a single patrol via PATROL_SERIAL_NUMBER) is inherited for
    free, since it's applied to patrols_df before this ever runs.
    """
    rows = [
        {
            "id": event["id"],
            "event_type": event["event_type"],
            "time": (event.get("geojson") or {}).get("properties", {}).get("datetime"),
            "geometry": shape(geom) if (geom := (event.get("geojson") or {}).get("geometry")) else None,
            "patrol_id": patrol["id"],
            "patrol_serial_number": patrol.get("serial_number"),
        }
        for _, patrol in patrols_df.iterrows()
        for segment in patrol["patrol_segments"] or []
        for event in segment.get("events") or []
    ]
    df = pd.DataFrame(rows, columns=["id", "event_type", "time", "geometry", "patrol_id", "patrol_serial_number"])
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    return gpd.GeoDataFrame(df, geometry="geometry", crs=4326)


# ---------------------------------------------------------------------------
hr(1, "Connect")
er = EarthRangerConnection.from_named_connection("belize").get_client()
print(f"Connected to {er.server}")

# "Report Generated by" is the ER account actually running this report, same
# pattern APN's patrol_event workflow uses (get_user_me -> client._get("user/me")),
# not a fabricated ranger name - the source PDF's "Julio Maaz" is whoever ran SMART's
# own export, which isn't something this account/pipeline can know or reproduce.
me = er._get("user/me")
generated_by = f"{me.get('first_name', '')} {me.get('last_name', '')}".strip() or me.get("username", "unknown")
generated_on = datetime.datetime.now()
report_meta = pd.DataFrame(
    [
        {
            "generated_by": generated_by,
            "generated_on": generated_on.strftime("%b %-d, %Y %-I:%M %p"),
            "report_start_date": SINCE.strftime("%b %-d, %Y"),
            "report_end_date": UNTIL.strftime("%b %-d, %Y"),
        }
    ]
)
print(f"  Report Generated by: {generated_by}    Generated on: {report_meta.iloc[0]['generated_on']}")

# ---------------------------------------------------------------------------
hr(2, f"Pull patrols, {SINCE.date()} to {UNTIL.date()}")
patrols = er.get_patrols(since=SINCE.isoformat(), until=UNTIL.isoformat())
print(f"{len(patrols)} patrols")

if PATROL_SERIAL_NUMBER is not None:
    patrols = patrols[patrols["serial_number"] == PATROL_SERIAL_NUMBER]
    if not len(patrols):
        raise ValueError(f"No patrol with serial_number={PATROL_SERIAL_NUMBER} in this window")
    print(f"  scoped to patrol serial_number={PATROL_SERIAL_NUMBER}: {patrols.iloc[0]['title']!r}")

# ---------------------------------------------------------------------------
hr(3, "Get ALL events attached to these patrols, then filter to report scope")
et_df = er.get_event_types()
et_display = dict(zip(et_df["value"], et_df["display"]))
id_lookup = dict(zip(et_df["value"], et_df["id"]))

# Events attached to a patrol are already embedded on the `patrols` DataFrame we
# fetched in step 2 (patrol_segments[].events) - patrol_events_gdf() unpacks them
# from there directly rather than calling get_patrol_events(), which would just
# re-fetch the exact same linkage over the network a second time. It does NOT
# include event_details (confirmed in explore_patrols_events.py), so full field
# values are still hydrated separately below, in bulk, only for the events this
# filters down to. Since `patrols` is already scoped to PATROL_SERIAL_NUMBER when
# set, this inherits that scoping for free - no separate patrol_id filter needed.
patrol_events = patrol_events_gdf(patrols)
print(f"  {len(patrol_events)} total events attached to patrols in this window (all types)")
if len(patrol_events):
    print(f"  by type: {patrol_events['event_type'].value_counts().to_dict()}")

patrol_events = patrol_events[patrol_events["event_type"].isin(EVENT_TYPE_KEYS)]
print(f"  {len(patrol_events)} events after filtering to report scope"
      f"{f' (patrol serial_number={PATROL_SERIAL_NUMBER})' if PATROL_SERIAL_NUMBER is not None else ''}")

detailed = er.get_events(
    since=SINCE.isoformat(), until=UNTIL.isoformat(),
    event_type=[id_lookup[k] for k in EVENT_TYPE_KEYS if k in id_lookup],
    include_details=True, drop_null_geometry=False,
)
detailed = detailed[detailed.index.isin(patrol_events["id"])]
details_by_id = detailed["event_details"].to_dict()

# The combined table: patrol_events (patrol_id, patrol_serial_number, event_type,
# time, geometry, ...) + a new event_details column, keyed onto each row by event
# id. This one flat DataFrame is now the single source of truth everything below
# reads from - not two separate objects joined ad hoc per call site.
patrol_events_combined = patrol_events.copy()
patrol_events_combined["event_details"] = patrol_events_combined["id"].map(details_by_id)
print(f"  patrol_events_combined: {len(patrol_events_combined)} rows, columns: {list(patrol_events_combined.columns)}")

# patrol_id -> event_type_key -> [ {id, time, geometry, **event_details}, ... ]
# (a grouped view of patrol_events_combined - kept because every table below
# already reads this shape; the combined DataFrame above is the real source.)
events_by_patrol: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
for _, row in patrol_events_combined.iterrows():
    events_by_patrol[row["patrol_id"]][row["event_type"]].append(
        {"id": row["id"], "time": row.get("time"), "geometry": row.get("geometry"), **(row.get("event_details") or {})}
    )
print(f"  {len(events_by_patrol)} distinct patrols have at least one in-scope attached event")

# ---------------------------------------------------------------------------
hr(4, "Resolve display names + color palette, all live from the account")

# Transport type (patrol.patrol_segments[].patrol_type, e.g. "boat_patrol") - straight
# off the account's own patrol-types list, same as every other patrol workflow uses.
pt_df = er.get_patrol_types()
transport_display = dict(zip(pt_df["value"], pt_df["display"]))
print(f"  transport types: {transport_display}")

# Patrol mandate (the patrol_details event's `patrol_mandate` field) has no
# get_*_types() endpoint of its own - it's a form field, not an ER-native concept.
# Its display names live in the account's own JSON-schema choices endpoint, the
# same one the patrol_details event schema's `patrol_mandate` property points at
# (schema["properties"]["patrol_mandate"]["anyOf"][0]["$ref"]) - resolved live here,
# not hand-copied from a one-time schema dump.
with er._use_v2_api():
    mandate_choices = er._get("schemas/choices.json?field=Patrol_Mandate")
mandate_display = {code: meta.get("display", code) for code, meta in (mandate_choices.get("x-enumExtra") or {}).items()}
print(f"  patrol mandates: {mandate_display}")

# Event type display names: already have et_display above, from the same
# get_event_types() call used to resolve event-type IDs for the fetch in step 3
# (ecoscope's own client also exposes this as
# EarthRangerIO.get_event_type_display_names_from_events() for appending
# `event_type_display` onto an events GeoDataFrame directly).
print(f"  event types in scope: {[et_display.get(k, k) for k in EVENT_TYPE_KEYS]}")

# Shared categorical palette: "tab20b" is the default `palette` on
# ecoscope.platform.tasks.config.set_chart.ChartStyle, i.e. what every
# ChartStyle-driven dashboard chart in this org uses unless a workflow overrides
# it. resolve_categorical_cmap_colors samples it into k evenly-spaced RGBA(0-255)
# colors; CATEGORY_ORDER's fixed order means a category keeps the same color
# across runs regardless of which categories happen to have data this month.
# RGBA(0-255) tuples, not hex - LegendFromDataframe/pydeck's color accessors read a
# per-row color column directly as an [r, g, b, a] value (see _color_tuple_to_css in
# _pydeck.py), so tuples are the native format here, not a string to convert later.
_category_rgba = resolve_categorical_cmap_colors("tab20b", len(CATEGORY_ORDER))
CATEGORY_COLOR_RGBA = dict(zip(CATEGORY_ORDER, _category_rgba))
print(f"  category palette: {CATEGORY_COLOR_RGBA}")

# ---------------------------------------------------------------------------
hr(5, "Assemble one row per patrol")
patrol_rows = []
for _, p in patrols.iterrows():
    segs = p["patrol_segments"] or []
    seg = segs[0] if segs else {}
    leader = (seg.get("leader") or {}).get("name")
    transport = seg.get("patrol_type")
    time_range = seg.get("time_range") or {}
    start_time = time_range.get("start_time")
    end_time = time_range.get("end_time")

    pe = events_by_patrol.get(p["id"], {})
    details = (pe.get("patrol_details") or [{}])[0]
    completion_list = pe.get("patrol_completion_log") or []
    completion = completion_list[0] if completion_list else {}
    mandate_code = details.get("patrol_mandate")

    patrol_rows.append(
        {
            "patrol_id": p["id"],
            "serial_number": p.get("serial_number"),
            "title": p.get("title"),
            "leader": leader,
            "transport_type": transport,
            "transport_type_display": transport_display.get(transport, transport or "(not set)"),
            "mandate_code": mandate_code,
            "mandate": mandate_display.get(mandate_code, mandate_code or "(not set)"),
            "start_time": start_time,
            "end_time": end_time,
            "fuel_used_gal": completion.get("fuel_used"),
            "vessel_inspected": completion.get("vessel_inspected"),
            "has_completion_log": bool(completion_list),
            "n_commercial_inspections": len(pe.get("commercial_fishing_vessels_inspections") or []),
            "n_recreational_vessels": len(pe.get("recreational_vessels") or []),
        }
    )
patrol_table = pd.DataFrame(patrol_rows)
patrol_table["start_time"] = pd.to_datetime(patrol_table["start_time"], utc=True, errors="coerce")
patrol_table["end_time"] = pd.to_datetime(patrol_table["end_time"], utc=True, errors="coerce")
patrol_table["duration_hours"] = (patrol_table["end_time"] - patrol_table["start_time"]).dt.total_seconds() / 3600
# Simple, explicit heuristic for "nights" pending the open question in the PRD:
# the patrol's start and end fall on different calendar dates.
patrol_table["nights"] = (patrol_table["end_time"].dt.date != patrol_table["start_time"].dt.date).astype("Int64")
print(patrol_table.drop(columns=["patrol_id"]).head(10).to_string())

# ---------------------------------------------------------------------------
# In single-patrol mode there's only one patrol to begin with, so the demo cap
# doesn't apply - compute its real track unconditionally rather than subsetting.
if PATROL_SERIAL_NUMBER is not None:
    hr(6, "Compute distance via trajectory for the selected patrol")
    recent = patrol_table.dropna(subset=["start_time"])
else:
    hr(6, f"Compute distance via trajectories for the {MAX_PATROLS_FOR_TRACKS} most recent patrols")
    recent = patrol_table.dropna(subset=["start_time"]).sort_values("start_time", ascending=False).head(MAX_PATROLS_FOR_TRACKS)
patrol_table["distance_km"] = pd.NA

track_segments = []
for _, prow in recent.iterrows():
    pid = prow["patrol_id"]
    p_df = patrols[patrols["id"] == pid]
    try:
        obs = er.get_patrol_observations(patrols_df=p_df, include_patrol_details=False)
        relocs = obs if isinstance(obs, Relocations) else Relocations.from_gdf(obs)
        if len(relocs.gdf) < 2:
            print(f"  {pid}: <2 GPS points, skipping distance")
            continue
        traj = Trajectory.from_relocations(relocs)
        tgdf = traj.gdf.copy()
        if not len(tgdf):
            continue
        dist_km = tgdf["dist_meters"].sum() / 1000
        patrol_table.loc[patrol_table["patrol_id"] == pid, "distance_km"] = round(dist_km, 2)
        tgdf["patrol_id"] = pid
        tgdf["mandate"] = prow["mandate"]
        tgdf["transport_type_display"] = prow["transport_type_display"]
        track_segments.append(tgdf)
        print(f"  {pid}: {len(tgdf)} track segments, {dist_km:.2f} km")
    except Exception as e:
        print(f"  {pid}: trajectory error: {e}")

tracks_gdf = gpd.GeoDataFrame(pd.concat(track_segments, ignore_index=True), crs=4326) if track_segments else None

# ---------------------------------------------------------------------------
hr(7, "Build report tables")

# --- Patrol Effort Summary (single-row stat card table) ---
patrol_effort_summary = pd.DataFrame(
    [
        {
            "number_of_patrols": len(patrol_table),
            "distance_km": round(patrol_table["distance_km"].dropna().astype(float).sum(), 2),
            "number_of_nights": int(patrol_table["nights"].fillna(0).sum()),
            "number_of_patrol_hours": round(patrol_table["duration_hours"].dropna().sum(), 2),
            "fuel_used_gal": round(patrol_table["fuel_used_gal"].dropna().astype(float).sum(), 2),
        }
    ]
)
print("\nPatrol Effort Summary:")
print(patrol_effort_summary.to_string(index=False))
if PATROL_SERIAL_NUMBER is None and len(recent) < len(patrol_table):
    print(
        "NOTE: distance_km/number_of_patrol_hours reflect only the "
        f"{len(recent)}-patrol demo subset with computed tracks, not all "
        f"{len(patrol_table)} patrols - see MAX_PATROLS_FOR_TRACKS."
    )

# --- Staff Effort ---
staff_effort = (
    patrol_table.groupby("leader", dropna=True)
    .agg(
        number_of_patrols=("patrol_id", "count"),
        number_of_nights=("nights", "sum"),
        distance_km=("distance_km", lambda s: round(s.dropna().astype(float).sum(), 2)),
        number_of_hours=("duration_hours", lambda s: round(s.dropna().sum(), 2)),
    )
    .reset_index()
    .rename(columns={"leader": "officer_name"})
    .sort_values("number_of_patrols", ascending=False)
)

# --- Patrols by Mandate (for chart + table) ---
patrols_by_mandate = patrol_table["mandate"].value_counts().rename_axis("mandate").reset_index(name="count")

# --- Recreational vessels, split by activity (fishing vs tourism) ---
# "id" (the event id) is dropped from every record - report tables show what a
# person reading the report needs, not an internal key (see 00_patrol_events_combined.csv
# for the full linkage if that's ever needed).
rv_rows = []
for eid_list in events_by_patrol.values():
    for rec in eid_list.get("recreational_vessels", []):
        rv_rows.append({k: v for k, v in rec.items() if k != "id"})
recreational_vessels = pd.DataFrame(rv_rows)
if len(recreational_vessels):
    activities = recreational_vessels.get("type_of_activities")
    is_fishing = activities.apply(lambda a: isinstance(a, list) and "recreational_fishing" in a) if activities is not None else pd.Series([], dtype=bool)
    is_tourism = activities.apply(lambda a: isinstance(a, list) and any(x in a for x in ("Snorkeling", "diving"))) if activities is not None else pd.Series([], dtype=bool)
    recreational_fishing_table = recreational_vessels[is_fishing] if activities is not None else recreational_vessels.iloc[0:0]
    recreational_tourism_table = recreational_vessels[is_tourism] if activities is not None else recreational_vessels.iloc[0:0]
else:
    recreational_fishing_table = pd.DataFrame(columns=["vessel_name", "vessel_registration_number", "number_of_passengers", "type_of_activities"])
    recreational_tourism_table = recreational_fishing_table.copy()

# --- Commercial fishing vessels encountered (flat) + fishers breakout ---
# n_infractions mirrors the PDF's "Infraction Detected" column (there, a flag; here,
# a count, since the live data is a full array of infraction records, not a boolean) -
# no separate Infractions table, matching the source report's own table set.
cfv_rows, fisher_rows = [], []
for pid, by_type in events_by_patrol.items():
    for rec in by_type.get("commercial_fishing_vessels_inspections", []):
        cfv_rows.append(
            {
                "vessel_name": rec.get("vessel_name"),
                "vessel_type": rec.get("vessel_type"),
                "vessel_home_port": rec.get("vessel_home_port"),
                "vessel_license_registration_number": rec.get("vessel_license_registration_number"),
                "name_of_captain": rec.get("name_of_captain"),
                "number_of_crew": rec.get("number_of_crew"),
                "type_of_inspection": rec.get("type_of_inspection"),
                "type_of_gear": rec.get("type_of_gear"),
                "n_infractions": len(rec.get("infractions") or []),
            }
        )
        for crew in rec.get("crew_members") or []:
            fisher_rows.append({"vessel_name": rec.get("vessel_name"), **crew})

commercial_fishing_vessels_encountered = pd.DataFrame(cfv_rows)
fishers_documented = pd.DataFrame(fisher_rows)

# --- Vessels Documented summary ---
# "station" is left blank, not hardcoded to a reserve name (e.g. "SWCMR") - there is
# no site/station field anywhere in the live schema (see PRD "Multi-site scope" / open
# question #6), and per feedback this is meant to become a user-supplied workflow
# config value later, not something this pipeline should guess or fill in.
vessels_documented = pd.DataFrame(
    [
        {
            "station": "",
            "recreational_fishing": len(recreational_fishing_table),
            "commercial_fishing": len(commercial_fishing_vessels_encountered),
            "subsistence_fishing": None,  # no matching field found anywhere - see PRD open question
            "tourism_vessel": len(recreational_tourism_table),
        }
    ]
)

# ---------------------------------------------------------------------------
hr(8, "Write tables to CSV")

write_csv(report_meta, "report_meta")

# The combined table itself, not just what's derived from it - event_details (a
# dict) and geometry (a shapely object) are stringified so the CSV stays plain text.
_combined_for_csv = patrol_events_combined.copy()
_combined_for_csv["event_details"] = _combined_for_csv["event_details"].apply(lambda d: json.dumps(d) if isinstance(d, dict) else d)
_combined_for_csv["geometry"] = _combined_for_csv["geometry"].apply(lambda g: g.wkt if g is not None and not pd.isna(g) else None)
write_csv(_combined_for_csv, "00_patrol_events_combined")

write_csv(patrol_effort_summary, "01_patrol_effort_summary")
write_csv(staff_effort, "02_staff_effort")
write_csv(patrols_by_mandate, "03_patrols_by_mandate")
write_csv(vessels_documented, "04_vessels_documented")
write_csv(recreational_fishing_table, "05_recreational_fishing_vessels")
write_csv(recreational_tourism_table, "06_recreational_tourism_vessels")
write_csv(commercial_fishing_vessels_encountered, "07_commercial_fishing_vessels_encountered")
write_csv(fishers_documented, "08_fishers_documented")
write_csv(patrol_table.drop(columns=["patrol_id"]), "09_patrols_detail")

# ---------------------------------------------------------------------------
hr(9, "Render charts")

# title=None on every chart - the docx/dashboard section heading already names each
# one (see build_docx_report.py's _heading() calls), so a second title baked into the
# chart itself would just duplicate it, same reasoning as draw_map's title below.
fig1 = bar_chart(patrols_by_mandate, bar_configs=[BarConfig(column="count", agg_func="sum", label="Patrols")], category="mandate", layout_kwargs={"title": None})
fig1.write_html(CHARTS_DIR / "patrols_by_mandate.html")
print(f"  wrote {CHARTS_DIR / 'patrols_by_mandate.html'}")

# Fixed CATEGORY_ORDER (not sorted by count) + the palette resolved in step 4, so
# slice colors match the map's point-layer colors for the same categories below,
# and stay stable run to run instead of being reassigned by whichever category
# happens to have the most records this month.
vessels_by_category = pd.DataFrame(
    [
        {"category": "Commercial Fishing", "count": len(commercial_fishing_vessels_encountered)},
        {"category": "Recreational Fishing", "count": len(recreational_fishing_table)},
        {"category": "Recreational Tourism", "count": len(recreational_tourism_table)},
    ]
)
# Bar, not pie - matches the source PDF's own "Type of Vessels Inspected" chart type.
# Unlike a pie chart, a 0-count category is a completely normal, unconfusing bar (just
# flat at the baseline), so zero-count categories are kept rather than dropped.
fig3 = bar_chart(
    vessels_by_category,
    bar_configs=[BarConfig(column="count", agg_func="sum", label="Vessels")],
    category="category",
    layout_kwargs={"title": None},
)
fig3.write_html(CHARTS_DIR / "vessels_by_category.html")
print(f"  wrote {CHARTS_DIR / 'vessels_by_category.html'}")

# ---------------------------------------------------------------------------
hr(10, "Render map (patrol tracks + event waypoints, legend split by patrol type / event type)")

# Same pattern as ICMBio-patrol_analysis/spec.yaml's "Patrol Coverage Map" task-group:
# one path layer for tracks, one scatterplot layer for events, each its own
# LegendFromDataframe (a *_color column on the geodataframe, referenced by name) so
# the two form separate legend boxes ("Patrol Type" / "Event Type") instead of one
# flat list - not a fixed color per layer, like the earlier create_polyline_layer/
# create_point_layer version had.
geo_layers = []

if tracks_gdf is not None and len(tracks_gdf):
    track_types = sorted(tracks_gdf["transport_type_display"].dropna().unique())
    track_type_rgba = dict(zip(track_types, resolve_categorical_cmap_colors("tab20b", len(track_types))))
    tracks_gdf = tracks_gdf.copy()
    tracks_gdf["track_color"] = tracks_gdf["transport_type_display"].map(track_type_rgba)
    geo_layers.append(
        create_path_layer(
            tracks_gdf,
            layer_style=PathLayerStyle(get_color="track_color", get_width=3),
            legend=LegendFromDataframe(title="Patrol Type", label_column="transport_type_display", color_column="track_color"),
            zoom=True,
        )
    )

# Recreational Fishing and Recreational Tourism both draw from the single
# `recreational_vessels` event type, split by activity - every other category maps
# 1:1 to its own event type. All 3 categories become rows in ONE combined
# GeoDataFrame (not 3 separate layers) so they share a single Event Type legend.
def _event_category(row) -> str | None:
    et = row["event_type"]
    if et == "commercial_fishing_vessels_inspections":
        return "Commercial Fishing"
    if et == "recreational_vessels":
        acts = (row.get("event_details") or {}).get("type_of_activities")
        if isinstance(acts, list):
            if "recreational_fishing" in acts:
                return "Recreational Fishing"
            if any(a in acts for a in ("Snorkeling", "diving")):
                return "Recreational Tourism"
    return None


events_with_geometry = patrol_events_combined.dropna(subset=["geometry"]).copy()
events_with_geometry["category"] = events_with_geometry.apply(_event_category, axis=1)
events_with_geometry = events_with_geometry.dropna(subset=["category"])
if len(events_with_geometry):
    events_with_geometry["category_color"] = events_with_geometry["category"].map(CATEGORY_COLOR_RGBA)
    events_with_geometry["event_type_display"] = events_with_geometry["event_type"].map(et_display).fillna(events_with_geometry["event_type"])
    events_gdf = gpd.GeoDataFrame(events_with_geometry, geometry="geometry", crs=4326)
    geo_layers.append(
        create_scatterplot_layer(
            events_gdf,
            layer_style=ScatterplotLayerStyle(get_fill_color="category_color", get_radius=6),
            legend=LegendFromDataframe(title="Event Type", label_column="category", color_column="category_color"),
            tooltip_columns=["event_type_display", "time"],
        )
    )

if geo_layers:
    # title=None - the docx/dashboard section heading already names this map;
    # draw_map's own docstring warns a second title here just duplicates that.
    html = draw_map(
        geo_layers=geo_layers,
        tile_layers=[TileLayer(url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", opacity=1)],
        title=None,
        legend_style=LegendStyle(placement="bottom-right"),
        output_type="html",
    )
    map_path = OUT_DIR / "map.html"
    with open(map_path, "w") as f:
        f.write(html)
    print(f"  wrote {map_path}  ({len(geo_layers)} layers)")
else:
    print("  no geometry-bearing layers available - skipping map")

# ---------------------------------------------------------------------------
hr(11, "Manifest")
print(f"Tables:  {sorted(p.name for p in TABLES_DIR.glob('*.csv'))}")
print(f"Charts:  {sorted(p.name for p in CHARTS_DIR.glob('*.html'))}")
print(f"Map:     {'map.html' if (OUT_DIR / 'map.html').exists() else '(not generated)'}")
print("\nDone.")
