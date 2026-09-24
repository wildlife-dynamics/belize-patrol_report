"""
Tests a cleaner view-state fitting function against patrol 11's real data -
the exact case that showed the track cutoff with compute_fitted_view_state
(ported from ecoscope-workflows-ext-wd).

Root cause (confirmed earlier this session): pydeck's own bbox_to_zoom_level
fits max(lng_diff, lat_diff) into a single SQUARE tile - no correction for
our map's actual WIDE (1280x720) aspect ratio, and no Mercator latitude
correction. For a small, diagonally-elongated track like patrol 11's, that
under-fits whichever axis isn't the larger of lat/lng.

This script's fit_view_to_geodataframes() reuses ICMBio-patrol_analysis's
proven math (separate zoom_for_lon/zoom_for_lat, taking the tighter one, with
a cos(latitude) Mercator correction and percentile-based outlier trimming) -
but generalized to accept multiple geodataframes directly (tracks + events in
one call), avoiding a separate concat_dataframes step in spec.yaml, and
using our REAL render size (1280x720, matching apn's html_to_png config)
instead of a dashboard-tile-sized default.

Run with:
  cd /Users/zak/Documents/w-dynamics/belize-patrol_report/ecoscope-workflows-belize-patrol-report-workflow
  pixi run python ../.scripts/test_view_state_fit.py
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd
from ecoscope.platform.connections import EarthRangerConnection
from ecoscope.platform.tasks.filter import TimeRange
from ecoscope.platform.tasks.filter._filter import TimezoneInfo
from ecoscope.platform.tasks.io._earthranger import get_events, get_patrol_observations
from ecoscope.platform.tasks.preprocessing._preprocessing import (
    process_relocations,
    relocations_to_trajectory,
)
from ecoscope.platform.tasks.results._pydeck import (
    LegendFromDataframe,
    LegendStyle,
    PathLayerStyle,
    ScatterplotLayerStyle,
    TileLayer,
    ViewState,
    create_path_layer,
    create_scatterplot_layer,
    draw_map,
)
from ecoscope.platform.tasks.transformation._filtering import Coordinate
from ecoscope_workflows_ext_custom.tasks.io._html_to_png import ScreenshotConfig, html_to_png

TARGET_SERIAL_NUMBER = 11
OUT_DIR = Path("/tmp/belize-view-state-fit-test")
_MAP_TILE_SIZE_PX = 256


def fit_view_to_geodataframes(
    geodataframes: list,
    width_px: int = 1280,
    height_px: int = 720,
    padding_fraction: float = 0.08,
    outlier_trim_percent: float = 1.0,
    max_zoom: float = 20.0,
) -> ViewState:
    """Fit a pydeck ViewState to the combined extent of MULTIPLE geodataframes
    at once (e.g. a map's track layer + its event layer together) - same
    math as ICMBio-patrol_analysis's own compute_view_from_geodataframes
    (separate per-axis zoom + Mercator correction + outlier trimming), just
    generalized to skip a separate concat_dataframes step, and defaulting to
    our actual render size instead of a dashboard-tile size."""
    non_empty = [gdf for gdf in geodataframes if gdf is not None and len(gdf) and not gdf.geometry.is_empty.all()]
    if not non_empty:
        return ViewState()

    coords = pd.concat([gdf.get_coordinates(ignore_index=True) for gdf in non_empty], ignore_index=True)
    if coords.empty:
        return ViewState()

    lon, lat = coords["x"].to_numpy(), coords["y"].to_numpy()
    trim = outlier_trim_percent
    lon_lo, lon_hi = np.percentile(lon, [trim, 100 - trim])
    lat_lo, lat_hi = np.percentile(lat, [trim, 100 - trim])
    lon_span = max(lon_hi - lon_lo, 1e-9)
    lat_span = max(lat_hi - lat_lo, 1e-9)
    center_lon, center_lat = (lon_lo + lon_hi) / 2, (lat_lo + lat_hi) / 2

    usable_width = width_px * (1 - 2 * padding_fraction)
    usable_height = height_px * (1 - 2 * padding_fraction)
    lat_correction = max(0.1, math.cos(math.radians(center_lat)))

    zoom_for_lon = math.log2(usable_width * 360 / (lon_span * _MAP_TILE_SIZE_PX * lat_correction))
    zoom_for_lat = math.log2(usable_height * 180 / (lat_span * _MAP_TILE_SIZE_PX))
    zoom = round(max(0.0, min(max_zoom, min(zoom_for_lon, zoom_for_lat))), 2)

    return ViewState(longitude=center_lon, latitude=center_lat, zoom=zoom, pitch=0.0, bearing=0.0)


client = EarthRangerConnection.client_from_named_connection("belize")
tz = TimezoneInfo(label="UTC", tzCode="UTC", name="UTC", utc="+00:00")
time_range = TimeRange(since="2026-02-01T00:00:00.000Z", until="2026-09-22T00:00:00.000Z", timezone=tz)

print("Resolving patrol id for serial_number =", TARGET_SERIAL_NUMBER, "...")
patrols_df = client.get_patrols(
    since=time_range.since.isoformat(), until=time_range.until.isoformat(), patrol_type_value=[], status=None
)
match = patrols_df[patrols_df["serial_number"].astype(str) == str(TARGET_SERIAL_NUMBER)]
assert len(match), f"No patrol with serial_number={TARGET_SERIAL_NUMBER}"
patrol_uuid = match.iloc[0]["id"]
print("patrol_id:", patrol_uuid)

print("Fetching patrol observations...")
obs = get_patrol_observations(
    client=client, time_range=time_range, patrol_types=[], include_patrol_details=True,
    raise_on_empty=False, sub_page_size=100, patrols_overlap_daterange=True,
)
obs = obs[obs["patrol_id"] == patrol_uuid].copy()
print("observations for this patrol:", len(obs))

relocs = process_relocations(
    observations=obs,
    relocs_columns=["patrol_id", "patrol_type__display", "groupby_col", "fixtime", "junk_status", "geometry"],
    filter_point_coords=[Coordinate(x=180.0, y=90.0), Coordinate(x=0.0, y=0.0), Coordinate(x=1.0, y=1.0)],
)
trajs = relocations_to_trajectory(relocations=relocs)
print("trajectory rows:", len(trajs))

print("Fetching commercial fishing events...")
events = get_events(
    client=client, time_range=time_range, event_types=["commercial_fishing_vessels_inspections"],
    include_details=True, include_display_values=True, include_null_geometry=False, raise_on_empty=False,
)

trajs["column_color"] = [(228, 26, 28, 255)] * len(trajs)
trajs["column_label"] = "Boat Patrol"
events = events.copy()
events["column_color"] = [(27, 158, 119, 255)] * len(events)
events["column_label"] = "Commercial Fishing Vessels Inspections"

track_layer = create_path_layer(
    geodataframe=trajs,
    legend=LegendFromDataframe(title="Patrol Type", label_column="column_label", color_column="column_color"),
    layer_style=PathLayerStyle(get_color="column_color", get_width=6, width_min_pixels=3),
)
event_layer = create_scatterplot_layer(
    geodataframe=events,
    legend=LegendFromDataframe(title="Event Type", label_column="column_label", color_column="column_color"),
    layer_style=ScatterplotLayerStyle(get_fill_color="column_color"),
)

view_state = fit_view_to_geodataframes([trajs, events])
print("fitted view_state:", view_state)

base_maps = [
    TileLayer(url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}", opacity=1),
    TileLayer(url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", opacity=0.5),
]

map_html = draw_map(
    geo_layers=[track_layer, event_layer],
    tile_layers=base_maps,
    view_state=view_state,
    static=False,
    title="Patrol 11 - new view-state fit",
    max_zoom=20,
    output_type="html",
    legend_style=LegendStyle(placement="bottom-right"),
)

OUT_DIR.mkdir(parents=True, exist_ok=True)
html_path = OUT_DIR / "patrol_11_fit.html"
html_path.write_text(map_html)
print(f"Wrote: {html_path}")

png_path = html_to_png(
    html_path=str(html_path),
    output_dir=str(OUT_DIR),
    config=ScreenshotConfig(full_page=False),
)
print(f"Wrote: {png_path}")
