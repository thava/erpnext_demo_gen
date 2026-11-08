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
      [--end-date YYYY-MM-DD] [--home-state TN] [--demo-company-name NAME] [--use-wizard-company]
      [--no-gst | --fictitious-gstin] [--force]
bench --site <site> demo-data status                          # what is installed now
bench --site <site> demo-data history [--run DD-RUN-00001]     # install/uninstall events, newest first
bench --site <site> demo-data verify [--run DD-RUN-00001]      # exits 1 if a check fails
bench --site <site> demo-data uninstall [--run DD-RUN-00001] [--registry-only] [--yes]
```

- Demo data goes into its own Company, made the default and registered as ERPNext's
  demo company, so the desk's **Delete Demo Data** button removes it too.
- `install` refuses a site that already has transactions, or has the GST API on,
  unless `--force`. For existing transactions the message says what installing
  would do: by default the demo goes into its own new company and leaves them
  unchanged, so `--force` is safe there. With `--use-wizard-company`, only that
  company's own transactions count: an unused wizard company needs no `--force`.
- Uninstall clears the whole demo company, including anything you created in it
  yourself while exploring.
- Re-running an interrupted `install` with the same options resumes it.
- Every created document is recorded in *Demo Data Record* under a *Demo Data Run*;
  `uninstall` uses that registry plus ERPNext's Transaction Deletion Record.
- `--use-wizard-company` generates into your existing company instead. If it is
  GST-registered (a company address with its GSTIN), its GST state is used as the
  home state. If not, pass `--fictitious-gstin` (adds a company address with a
  made-up GSTIN, removed on uninstall) or `--no-gst --force`. Uninstall then removes
  only the run's own documents, one by one, and keeps (and reports) any that your
  own documents refer to. `--registry-only` uses the same one-by-one removal for a
  demo company.
- `--no-gst` (with `--force`) generates for a company not registered for GST. See
  [Unregistered businesses](#unregistered-businesses-no-gst) below.

## Unregistered businesses (no GST)

Many small businesses using ERPNext are not registered for GST. `--no-gst --force`
generates a demo for one. **ERPNext and india_compliance do not handle this case by
themselves. The demo does what such a business has to set up by hand, described
below.**

What happens in ERPNext when the company has no GSTIN:

- india_compliance treats the company as unregistered and turns off all its GST
  logic: no tax templates are picked and no GST checks run.
- Sales carry no GST, which is right: an unregistered business does not charge it.
- Purchases from GST-registered suppliers **still include GST**, and an unregistered
  business cannot claim it back (no input tax credit), so it is part of what the
  goods cost. ERPNext does not do this by default: unless you set it up, the
  purchase has no GST at all and the amount owed to the supplier is too low.

**Setup required: no-ITC purchase templates.** The demo creates these two, and a
real unregistered company needs the same:

| Template | Rows |
| --- | --- |
| Input GST In-state (no ITC) | CGST and SGST, as in "Input GST In-state" |
| Input GST Out-state (no ITC) | IGST, as in "Input GST Out-state" |

To make one: open *Purchase Taxes and Charges Template*, duplicate india_compliance's
"Input GST In-state" (or "Out-state") template of your company, rename it, and in
every row set **Consider Tax or Charge for** to **Valuation and Total** (Add or
Deduct: Add). Leave Tax Category empty. "Valuation and Total" adds the GST to the
item's valuation rate, so stock value and cost of goods sold include it; each
item's GST rate still comes from its Item Tax Template.

Then, on each purchase order (or purchase invoice) from a GST-registered supplier,
select the in-state template when the supplier is in your state and the out-state
one otherwise. Receipts and invoices made from the order copy the tax rows.
Purchases from unregistered suppliers get no template.

To have ERPNext pick the template by itself, add two *Tax Rules* (Tax Type:
Purchase, your company): one with Billing State set to your state and the in-state
template, and one with no state and the out-state template; the more specific rule
wins. A rule only matches suppliers with the same Tax Category (empty matches
empty), so give your unregistered suppliers a Tax Category such as "Unregistered"
and no rule applies to them. Do not simply mark a template as default: it would
also add GST to purchases from unregistered suppliers.

Other rules the demo follows:

- **Customers only in your state.** Supplying goods to another state, or to an SEZ,
  needs GST registration at any turnover, so the demo has no such sales. Suppliers
  can be anywhere.
- **Turnover above the threshold.** The demo uses the pack's normal volume, above
  the registration threshold (Rs 40 lakh a year for goods, Rs 20 lakh in
  special-category states). Install prints a warning: a real business that size
  must register.
- **Your own company.** With `--use-wizard-company --no-gst`, the two templates are
  created in your company and removed on uninstall, unless your own documents use
  them by then; those are kept and reported. To keep using the templates after
  uninstall, create your own copies as above.
- `verify` checks that sales carry no GST and that purchases from registered
  suppliers carry GST rows marked "Valuation and Total".

## Sizes

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
