# Belize Patrol Report

Belize Fisheries Department — EarthRanger monthly patrol & vessel monitoring report, replicating the department's existing SMART Monthly Report format, for all of the department's protected areas on the shared `belize` EarthRanger account (`https://sacdbelize.pamdas.org`), not just one site.

`SWCMR_Report_000054.pdf` (South Water Caye Marine Reserve, titled "SMART Monthly Report" on the PDF itself) was only the **example** used to work out the target format and field mapping — this workflow replicates that report's layout and fields, not SMART Connect itself; everything comes straight out of EarthRanger. The account's patrol activity spans multiple sites (patrol titles reference Corozal Bay, Shipstern, New River, and others), so the workflow is site-general rather than scoped to one protected area.

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
