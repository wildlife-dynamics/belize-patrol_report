# Belize-patrol_report

Belize Fisheries Department — EarthRanger monthly patrol & vessel monitoring report, replicating the department's existing report format, for all of the department's protected areas on the shared `belize` EarthRanger account (`https://sacdbelize.pamdas.org`), not just one site.

`SWCMR_Report_000054.pdf` (South Water Caye Marine Reserve, titled "SMART Monthly Report" on the PDF itself) is only the **example** used to work out the target format and field mapping — we're replicating this report's layout and fields, not integrating with SMART Connect itself; everything comes straight out of EarthRanger. The live account's actual patrol activity in this window is from a different site (patrol titles reference Corozal Bay / Shipstern / New River, not South Water Caye), confirming multiple sites share this one account. The workflow needs to be site-general, not SWCMR-specific: see the PRD's "Multi-site scope" note.

- `PRD - Belize SWCMR.md` — requirements, verified against the live `belize` EarthRanger account
- `.scripts/` — exploration + output-generation scripts that pulled the field mapping and produced real tables/charts/map from live data

Workflow scaffold (spec.yaml, dags, docx template) is the next phase, pending the open questions in the PRD — including how a "site" is actually identified in the data (no station/region field found yet; still open).