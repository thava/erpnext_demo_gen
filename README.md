# Demo Data

Realistic, removable India demo data for ERPNext v16+.

Status: Phase 1. `install` creates a demo company with its India set-up, masters
and a year (Small) or two (Medium) of purchases, sales, payments, returns and
open items; `verify` checks the result; `uninstall` removes it. Packs:
`furniture_store` and `electrical_distributor`. The requirements and design live
in the bench folder: `demo-data-req-design.md`.

## Requirements

frappe and erpnext v16+, india_compliance, a finished setup wizard, and a running
Redis queue (ERPNext's Transaction Deletion Record needs it).

## Usage

```bash
bench --site <site> demo-data list-packs
bench --site <site> demo-data install --pack furniture_store [--size small|medium] [--seed N] \
      [--end-date YYYY-MM-DD] [--home-state "Tamil Nadu"] [--company NAME] [--use-wizard-company] [--force]
bench --site <site> demo-data status
bench --site <site> demo-data verify [--run DD-RUN-00001]      # exits 1 if a check fails
bench --site <site> demo-data uninstall [--run DD-RUN-00001] [--yes]
```

- Demo data goes into its own Company, made the default and registered as ERPNext's
  demo company, so the desk's **Delete Demo Data** button removes it too.
- `install` refuses a site that already has transactions, or has the GST API on,
  unless `--force`.
- Re-running an interrupted `install` with the same options resumes it.
- Every created document is recorded in *Demo Data Record* under a *Demo Data Run*;
  `uninstall` uses that registry plus ERPNext's Transaction Deletion Record.

Sizes, measured on a laptop at about 0.22 s per document:

| Pack | Small (12 months) | Medium (24 months) |
| --- | --- | --- |
| furniture_store | about 900 documents, 4 minutes | about 16,000 documents, about an hour |
| electrical_distributor | about 1,250 documents, 5 minutes | about 20,000 documents, about 75 minutes |

## Development

```bash
bench --site demo-data.localhost run-tests --app demo_data       # unit tests (planner, packs, generators)
bench --site demo-data.localhost execute demo_data.tests.smoke.run \
      --kwargs '{"pack": "furniture_store", "seed": 11}'          # install, verify, uninstall, compare counts
```

`dev/phase0_spike.py` is the Phase 0 runtime spike (see section 6.2 of the design).

## License

GPL-3.0
