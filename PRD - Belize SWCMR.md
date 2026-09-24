# PRD - Belize Fisheries Department: SWCMR Patrol & Vessel Monitoring Report

**Partner:** Belize Fisheries Department — South Water Caye Marine Reserve (SWCMR)
**Platform:** EarthRanger (source data) → Ecoscope (workflow / report generation)
**ER connection:** named connection `belize` → `https://sacdbelize.pamdas.org`
**Source report:** `SWCMR_Report_000054.pdf` — the partner's existing report (titled "SMART Monthly Report" on the PDF itself, but that's just the document's own name — this is a replication exercise off data already in EarthRanger, not a SMART Connect integration), used as the target layout for the docx output and as the starting field list for the dashboard.
**Language:** English

All field names, choice lists and record counts below were pulled live from the `belize` EarthRanger account on 2026-09-22 via the scripts in `.scripts/` — nothing here is guessed from the PDF alone. See "Data Verified Live" at the end for the raw numbers and how to reproduce them.

## Multi-site scope (important correction)

`SWCMR_Report_000054.pdf` is an **example** report, not the only site this workflow needs to cover. The `belize` EarthRanger account is shared across the Fisheries Department's protected areas generally, not scoped to South Water Caye alone — confirmed by the live data itself: the patrols pulled for this PRD's verification (Feb–Sep 2026) have titles referencing Corozal Bay, Shipstern Lagoon/Caye, New River, Consejo Shores and Rocky Point, all in northern Belize near the Mexican border, geographically nowhere near South Water Caye Marine Reserve (which sits off the central coast near Dangriga). So the account's real, current patrol activity is from a *different* site than the one the example PDF describes.

Everything else in this PRD — the patrol/event schema, the field mappings, the mandate/vessel/fisher tables — is confirmed to be **site-agnostic**: `patrol_details`, `patrol_completion_log`, `recreational_vessels`, `commercial_fishing_vessels_inspections`, `fishing_gear_removed_from_pa`, and `cargo_or_other_types_of_vessesls` are account-wide event types, not scoped to one reserve, so the data model itself needs no rework.

What does need rework before scaffolding: **there is no "site" or "station" field anywhere in the schema.** Checked and ruled out:
- Patrol / event records themselves: no station/site/region property on any of the 6 event types or on the patrol object.
- Ranger subjects: all 13 rangers sit in a single ER subject group ("Rangers"), and each subject's `additional.region`/`additional.country` fields are blank.

So a "which site is this patrol/report for" scoping mechanism is still an open question — most likely candidates, to check next: (a) a spatial join against each protected area's boundary (the pattern every other org workflow uses for AOI filtering, e.g. ICMBio's `aoi_filter`), if reserve boundaries exist as ER spatial features on this account; or (b) asking the partner directly how they currently distinguish sites when producing that report today, since the source PDF clearly does show a single site's name ("SWCMR") somewhere even though it isn't in the ER data we can see. This blocks a real "Station" column/filter and needs to be resolved before the workflow can be more than single-account-wide (i.e. "all patrols on this belize account", not "all patrols at reserve X").

The static "Background" text and logos below are still a good pattern for a per-site "About this site" block — they just need to become a *per-site* parameter (config keyed by whichever site-identification mechanism gets resolved above) rather than one hardcoded paragraph, once there's more than one site's boilerplate to support.

---

## Background (static report text)

The source PDF opens with a fixed descriptive paragraph about the reserve (size, location, legal establishment, staffing). This is boilerplate that doesn't change month to month — it should be a static block in the docx template (and an "About this site" panel on the dashboard), not computed from ER data:

> South Water Caye Marine Reserve is managed by the Belize Fisheries Department and is one of the largest marine protected areas in Belize. It covers 508.341 km² (~50,934 hectares)... established in 1996 under SI 118, under the Fisheries Act (Ch 210, 1983). Staffed by a Manager, a biologist, two park rangers, and a caretaker at the Twin Cayes Ranger Station.

Only the two logos (Belize Fisheries Dept, SWCMR reserve crest) and this text need to be supplied once as report assets/config — no open question, just an asset to collect from the user before docx templating.

---

## Implementation Approach

One workflow, parameterized by a reporting period (defaults to calendar month, like the PDF), built entirely from **patrols** and the **events attached to patrols** on the `belize` ER account. This is a replication exercise off data already in EarthRanger, not a SMART Connect integration — everything needed is already there as patrols + patrol-linked events, no separate system to reach into.

Key findings that shape the build (all confirmed live, not assumed):

* **Patrol "mandate" is an event field, not a patrol field.** `Patrol.patrol_segments[].patrol_type` is only the transport mode (`boat_patrol`, `foot_patrol`, `Vehicle_Patrol`, `bicycle_patrol`). The report's "Patrols by Mandate" category (Day Patrol, Night Patrol, Joint Patrol, ...) actually lives on the **`patrol_details`** event's `patrol_mandate` field — one `patrol_details` event exists per patrol (88 patrols, 88 `patrol_details` events in the last 12 months). Confirms the user's framing: every patrol carries a `patrol_details` event.
* **The live mandate choice list has drifted from the PDF's list.** Current live choices: `DayPatrol`, `NightPatrol`, `JointPatrol`, `BeachTrap`, `CoastalDevelopmentMonitoring`, `InteligenceResponse`, `TransboundaryPatrol`. The PDF instead shows `Logistics Support`, `Monitoring`, `Shift Change`, `Spags Patrol`. The `patrol_mandate` field's choice list has clearly been reconfigured in ER since that PDF was generated — **build against the live schema**; flag this drift to the partner rather than trying to reproduce the old categories.
* **Distance, duration and "nights" are not raw fields anywhere.** `Patrol` and `patrol_segments` carry `time_range` (start/end timestamp) and `start_location`/`end_location`, but no distance. This must be computed the same way every other patrol workflow in this org does it: `get_patrol_observations_with_patrol_filter` → `Relocations` → `Trajectories` → summed segment length for distance, and `time_range` span for duration. "Nights" needs a derivation rule (e.g. `time_range` crossing a calendar-day boundary, or end_time − start_time > 20h) — **open question for the partner**, no explicit field to read it from.
* **The "patrol completion log" is its own event type**, confirming the user's framing exactly: `patrol_completion_log` (fuel_used, vessel_inspected, equipment_returned_and_stored, notes_of_patrol) exists on 37 of the 88 patrols in the last 12 months — not every patrol gets one logged; the workflow must handle patrols with no completion log.
* **One `recreational_vessels` event type covers what the PDF splits into two tables.** "Recreational Fishing Vessels" vs "Recreational Tourism Vessels" are the same event type, distinguished by `type_of_activities` (choices: `Snorkeling`, `diving`, `recreational_fishing`) — filter/group by that field rather than expecting two separate forms.
* **`commercial_fishing_vessels_inspections` is richer than the PDF's flat table.** Beyond vessel/captain/crew-count, it carries nested arrays: `catch_inspections` (species/state/quantity), `crew_members` (name_of_fisher, license_number — this is the PDF's separate "Fishers Documented" table), `infractions` (offender, type, action taken), `product_seized`, `equipment_siezed`. Recommend surfacing these as expandable detail rather than dropping them to match the PDF's flatter layout.
* **"Fishers Documented" has no QR/ID field.** The PDF's columns (QR NAME/License Number, Name, Id Number) map only to `crew_members[].{name_of_fisher, license_number}` inside commercial inspections — there's no standalone fisher-ID or QR capture in this schema. Table will show name + license number only; flag the gap.
* **No "Joint Patrol Team" event type exists.** The PDF's table is empty in the sample month, consistent with this: there's no dedicated form for it. `patrol_details.patrol_members` (a list of subject IDs) plus `.agencyorganization`/`.rank`/`.name_of_officer` is the closest available data, but only really means something when a patrol is jointly conducted (`patrol_mandate = JointPatrol`, 1 record in the last 12 months). **Open question for the partner:** keep this table only for joint-mandate patrols, or drop it.
* **Two bonus event types have real data but aren't in the sample PDF at all:** `fishing_gear_removed_from_pa` (type of gear, quantity, species found in gear — 5 records/yr) and `cargo_or_other_types_of_vessesls` (captain, vessel name, activity type, notes — 4 records/yr). Recommend adding both as optional sections since the data already exists and is being collected in the field.

---

## Dashboard / Report Features

### Report header / metadata
* Site background text + logos (static, see above)
* Report period (start/end date), generated-by (report author), generated-on (timestamp) — mirrors the PDF's header block

### Patrol Effort Summary (stat cards)
* Number of patrols
* Total distance patrolled (km) — computed from trajectories, see above
* Number of nights — derivation TBD, see open question
* Total patrol hours — from summed `time_range` durations
* Fuel used (gallons) — summed from `patrol_completion_log.fuel_used` (only patrols with a completion log contribute; note partial coverage)

### Staff Effort (table)
* Columns: Officer name, # patrols, # nights, distance (km), # hours
* Officer identity: `patrol_details.patrol_leader` (subject reference) or `patrol_segments[].leader` — resolve to subject display name
* Grouped/summed per officer across the reporting period

### Charts
* Bar chart: Patrols by Mandate (`patrol_details.patrol_mandate`, live choices above)
* Bar chart: Patrols by Transport Type (`patrol_segments.patrol_type`: boat/foot/vehicle/bicycle) — not in the original PDF, but real and free given the data; recommend adding
* Bar chart: Vessels documented by type (recreational-fishing / recreational-tourism / commercial / cargo), counted across the four vessel-related event types

### Vessels Documented (summary table)
* Columns: Station, Recreational Fishing count, Commercial Fishing count, Subsistence Fishing count, Tourism Vessel count
  * "Subsistence Fishing" has no matching event type or field found anywhere in the schema — **open question for the partner**: confirm whether this category is actually captured, or drop the column.
  * "Station" — no per-record station/site field was found on any of the 5 event types; likely a fixed value (single-station reserve) rather than a real grouping field — confirm with partner.

### Recreational Fishing Vessels (table)
* Source: `recreational_vessels` where `type_of_activities` includes `recreational_fishing`
* Columns: Vessel name, vessel registration number, # passengers, activity type(s), origin of tour *(no "origin of tour" field found on this event type — PDF may be filling it manually or it's a gap; flag)*

### Recreational Tourism Vessels (table)
* Source: `recreational_vessels` where `type_of_activities` includes `Snorkeling` or `diving`
* Same columns as above
* **Coverage warning:** only 1 `recreational_vessels` record exists on the account in the last 24 months (vs. ~30 rows in the sample PDF for tourism vessels alone). Either this data is captured elsewhere (a different event type not yet identified) or reporting into this form has lapsed — confirm with the partner before building against it as a primary table.

### Commercial Fishing Vessels Encountered (table)
* Source: `commercial_fishing_vessels_inspections` (18 records / 12mo)
* Columns: Vessel name, vessel type (choices: Canoe/Catamaran/Sailboat/Skiff), home port, license/registration #, captain, # crew, type of inspection (choices: Catch only / Documents Only / Full Inspection / Meet and greet only), gear types, infraction(s) detected
* Expandable/nested detail: catch inspections, product seized, equipment seized (real data not in the PDF's flat version)

### Fishers Documented (table)
* Source: `commercial_fishing_vessels_inspections.crew_members[]`
* Columns: Name, License number *(no QR / separate ID number field — see gap above)*

### Fishing Gear Removed from Protected Area (table) — recommended addition
* Source: `fishing_gear_removed_from_pa` (5 records/yr)
* Columns: type of gear, quantity, species found in gear (species/qty)

### Cargo / Other Vessels (table) — recommended addition
* Source: `cargo_or_other_types_of_vessesls` (4 records/yr)
* Columns: vessel name, captain, activity type, notes

### Map of Activities Documented
* Patrol tracks for the period (from patrol observations/trajectories), coloured by mandate or transport type
* Event waypoints coloured by category (commercial fishing / recreational / gear removed / cargo), matching the PDF's legend style
* AOI/reserve boundary layer (South Water Caye Marine Reserve) — need to confirm the boundary is available as an ER spatial feature or must be supplied as a static GeoJSON, same pattern as the Iguaçu park-boundary file

---

## Open Questions for the Partner

1. How should "Nights" be derived — is there a field/convention the partner's old report used that ER doesn't expose, or should it be computed from `time_range` span?
2. Is "Subsistence Fishing" actually captured anywhere, or should that column be dropped from the Vessels Documented summary?
3. Is the near-total absence of `recreational_vessels` records (1 in 24 months) a data-entry gap, or is recreational-vessel data coming from a different source than the one this account exposes?
4. Should the Joint Patrol Team table be kept (populated only for `JointPatrol`-mandate patrols) or dropped, given no dedicated event type exists?
5. Confirm the reserve boundary/AOI source for the map layer, and supply the two report logos + exact static background paragraph text for the docx template — per site, once #6 is resolved.
6. **(new, see "Multi-site scope" above)** How does the partner identify which site/reserve a given patrol belongs to today? No station/site/region field exists anywhere in the live schema - this blocks per-site "Station" columns, per-site "About this site" boilerplate, and possibly the whole report needing an AOI-based patrol filter rather than running over the whole account at once.

---

## Data Verified Live

Connection: `belize` → `https://sacdbelize.pamdas.org`, queried 2026-09-22, primary window 2025-09-22 → 2026-09-22 (the PDF's own period, Feb 2026, returned 0 patrols/events on this account — the account's data starts later than that sample report; verification used the last 12 months of real data instead).

| Event type | Category | Records (12mo) | Records (24mo) |
|---|---|---|---|
| `patrol_details` | patrol_details | 88 | 88 |
| `patrol_completion_log` | patrol_details | 37 | 37 |
| `commercial_fishing_vessels_inspections` | patrol_details | 18 | 18 |
| `fishing_gear_removed_from_pa` | patrol_details | 5 | — |
| `cargo_or_other_types_of_vessesls` | patrol_details | 4 | — |
| `recreational_vessels` | patrol_details | 1 | 1 |

Patrols: 88 total in 12mo, all `state=done`. Transport type breakdown: `boat_patrol` 82, `foot_patrol` 6. Mandate breakdown (from `patrol_details.patrol_mandate`): `DayPatrol` 52, `BeachTrap` 10, `NightPatrol` 9, `TransboundaryPatrol` 5, `CoastalDevelopmentMonitoring` 3, `JointPatrol` 1, `InteligenceResponse` 1, unset 7.

Reproduce with:
```
cd ICMBio-patrol_analysis/ecoscope-workflows-patrol-analysis-workflow
pixi run --locked -e default python ../../belize-patrol_report/.scripts/explore_patrols_events.py
pixi run --locked -e default python ../../belize-patrol_report/.scripts/explore_event_schemas.py
pixi run --locked -e default python ../../belize-patrol_report/.scripts/explore_choices_and_segments.py
```
(This project has no compiled pixi env of its own yet — these scripts borrow ICMBio-patrol_analysis's, same pattern as Iguaçu/Curacao's `.scripts` reference each other's compiled envs. Once this workflow is scaffolded for real, point at its own env instead.)

---

## Next Step

This PRD covers requirements + verified data shape only. Scaffolding the actual `ecoscope-workflows` package (spec.yaml, dags, docx template, layout.json) is the next phase, once the open questions above are resolved with the partner — in particular #1 (nights) and #3 (recreational vessel coverage) materially affect which stat cards and tables can ship in v1.
