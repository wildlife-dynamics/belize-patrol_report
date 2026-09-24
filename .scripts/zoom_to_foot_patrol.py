"""
Zooms straight to the one Foot Patrol GPS track in the belize account's data
(currently a single ~49m segment, patrol id 3f2d1438-9de9-43ef-bddc-7aae7c3fd042)
to visually confirm it's real and see where it sits relative to the dense
Boat Patrol cluster it's likely hidden under in the full report map.

Rebuilds the exact same observations -> relocs -> trajs pipeline
ecoscope_workflows_ext_belize.tasks (via spec.yaml) uses, filters to just this
one patrol, then renders a tightly-zoomed pydeck map + PNG - no workflow
compile needed, just the already-installed packages in the compiled
workflow's own pixi env.

Run with:
  cd /Users/zak/Documents/w-dynamics/belize-patrol_report/ecoscope-workflows-belize-patrol-report-workflow
  pixi run python ../.scripts/zoom_to_foot_patrol.py
"""

from pathlib import Path

import pandas as pd
from ecoscope.platform.connections import EarthRangerConnection
from ecoscope.platform.tasks.filter import TimeRange
from ecoscope.platform.tasks.filter._filter import TimezoneInfo
from ecoscope.platform.tasks.io._earthranger import get_patrol_observations
from ecoscope.platform.tasks.preprocessing._preprocessing import (
    process_relocations,
    relocations_to_trajectory,
)
from ecoscope.platform.tasks.results._pydeck import (
    LegendFromDataframe,
    PathLayerStyle,
    TileLayer,
    ViewState,
    create_path_layer,
    draw_map,
)
from ecoscope.platform.tasks.transformation._filtering import Coordinate
from ecoscope_workflows_ext_custom.tasks.io._html_to_png import ScreenshotConfig, html_to_png

TARGET_PATROL_ID = "3f2d1438-9de9-43ef-bddc-7aae7c3fd042"
OUT_DIR = Path("/tmp/belize-foot-patrol-zoom")

client = EarthRangerConnection.client_from_named_connection("belize")

tz = TimezoneInfo(label="UTC", tzCode="UTC", name="UTC", utc="+00:00")
time_range = TimeRange(since="2026-02-01T00:00:00.000Z", until="2026-09-22T00:00:00.000Z", timezone=tz)

print("Fetching patrol observations (same params as the real workflow)...")
obs = get_patrol_observations(
    client=client,
    time_range=time_range,
    patrol_types=[],
    include_patrol_details=True,
    raise_on_empty=False,
    sub_page_size=100,
    patrols_overlap_daterange=True,
)

relocs = process_relocations(
    observations=obs,
    relocs_columns=["patrol_id", "patrol_type__display", "groupby_col", "fixtime", "junk_status", "geometry"],
    filter_point_coords=[Coordinate(x=180.0, y=90.0), Coordinate(x=0.0, y=0.0), Coordinate(x=1.0, y=1.0)],
)
trajs = relocations_to_trajectory(relocations=relocs)

foot_patrol_trajs = trajs[trajs["extra__patrol_id"] == TARGET_PATROL_ID].copy()
print(f"Foot Patrol segments found: {len(foot_patrol_trajs)}")
if not len(foot_patrol_trajs):
    raise SystemExit(f"No trajectory rows found for patrol_id={TARGET_PATROL_ID} - it may have moved/changed.")
print(foot_patrol_trajs[["extra__patrol_type__display", "dist_meters", "geometry"]])

foot_patrol_trajs["column_color"] = [(214, 39, 40, 255)] * len(foot_patrol_trajs)  # solid red, unmissable
foot_patrol_trajs["column_label"] = "Foot Patrol"

layer = create_path_layer(
    geodataframe=foot_patrol_trajs,
    legend=LegendFromDataframe(title="Patrol Type", label_column="column_label", color_column="column_color"),
    layer_style=PathLayerStyle(get_color="column_color", get_width=8, width_min_pixels=4),
)

# Centered directly on the segment's own midpoint, at a tight zoom - not an
# auto-fit over the whole report's much larger Boat Patrol extent.
bounds = foot_patrol_trajs.total_bounds  # minx, miny, maxx, maxy
center_lon = (bounds[0] + bounds[2]) / 2
center_lat = (bounds[1] + bounds[3]) / 2
view_state = ViewState(longitude=center_lon, latitude=center_lat, zoom=18, pitch=0, bearing=0)

base_maps = [
    TileLayer(url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", opacity=1)
]

map_html = draw_map(
    geo_layers=[layer],
    tile_layers=base_maps,
    view_state=view_state,
    static=False,
    title="Foot Patrol - zoomed",
    max_zoom=20,
    output_type="html",
)

OUT_DIR.mkdir(parents=True, exist_ok=True)
html_path = OUT_DIR / "foot_patrol_zoom.html"
html_path.write_text(map_html)
print(f"Wrote: {html_path}")

png_path = html_to_png(
    html_path=str(html_path),
    output_dir=str(OUT_DIR),
    config=ScreenshotConfig(
        width=1000, height=800, full_page=True, device_scale_factor=2,
        wait_for_timeout=8000, timeout=0, max_concurrent_pages=1, serve_local_files=False,
    ),
)
print(f"Wrote: {png_path}")
