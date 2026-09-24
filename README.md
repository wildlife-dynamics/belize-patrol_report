# Belize Patrol Report

Belize Fisheries Department patrol and vessel-inspection report, pulling patrols and events from the `belize` EarthRanger account (`https://sacdbelize.pamdas.org`). Patrol titles in the data reference Corozal Bay, Shipstern, New River, and other sites on this account, so the workflow reports across all of them for the selected time range rather than filtering to one.

It produces a dashboard (patrol/staff effort tables, patrols-by-mandate and vessels-inspected charts, per-category vessel and fisher tables, a map of patrol tracks and events) and a `.docx` report combining the same tables and charts with photos downloaded from EarthRanger event attachments.

## Dashboard widgets

| Widget | Description |
|--------|-------------|
| Patrol Effort Summary | Totals across all patrols in scope: number of patrols, distance (km), nights, patrol hours, fuel used |
| Staff Effort | Per-officer table: number of patrols, nights, distance (km), hours |
| Patrols by Mandate | Bar chart of patrol counts by mandate |
| Type of Vessels Inspected | Bar chart of vessel inspection counts by category |
| Vessels Documented | Counts by vessel category: recreational fishing, commercial fishing, subsistence fishing, tourism |
| Recreational Fishing Vessels | Table of documented recreational fishing vessel inspections |
| Recreational Tourism Vessels | Table of documented recreational tourism vessel inspections |
| Commercial Fishing Vessels Encountered | Table of documented commercial fishing vessel inspections and their fishers |
| Fishers Documented | Table of fishers encountered during commercial fishing inspections |
| Map of Activities Documented | Map of patrol tracks and events, colored by the configured Patrol Style / Event Style groupby, view fit automatically to the data in scope (see Viewstate below) |

## Word report

Beyond the dashboard, this workflow generates a `.docx` report (via `generate_belize_patrol_report`) combining the map, patrol/vessel/fisher tables, charts, and event attachment photos downloaded from EarthRanger, using a Jinja/docxtpl template (`resources/templates/belize_patrol_report_template.docx`, built by `.scripts/build_report_template.py`, not itself tracked in this repository — see `.gitignore`).

## Scoping to a single patrol

The "Patrol Serial Number" parameter (`patrol_id_filter`) is optional and blank by default, in which case the report covers every patrol in the selected time range. Set it to a specific patrol's serial number to scope the whole report — patrol tables, map track, vessel/fisher tables, and map events — to just that one patrol.

## Viewstate

The map's view (center + zoom) is fit automatically to whatever data is in scope (`fit_view_to_geodataframes`), correcting for the map's actual wide render aspect ratio and Mercator latitude distortion so tracks aren't clipped on tighter, single-patrol views. Padding, outlier trimming, and max zoom are exposed as advanced parameters under "Viewstate" for cases where the automatic fit needs adjusting.

## Requirements

[pixi](https://pixi.sh) is required for environment and dependency management. You will also need an EarthRanger connection configured for the `belize` data source.

- `dev/recompile.sh` / `make recompile` — full recompile after any spec.yaml or ext-belize task change
- `dev/regenerate_rjsf.sh` — fast schema-only regeneration (form/rjsf.json) without a full recompile
- `make run` — run the workflow against `param.yaml` with real data
