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
bench --site <site> demo-data install --pack furniture_store [--size micro|small|medium] [--seed N] \
      [--end-date YYYY-MM-DD] [--home-state TN] [--demo-company-name NAME] [--use-wizard-company]
      [--no-gst | --fictitious-gstin] [--force]
bench --site <site> demo-data status                          # what is installed now
bench --site <site> demo-data history [--run DD-RUN-00001]     # install/uninstall events, newest first
bench --site <site> demo-data verify [--run DD-RUN-00001]      # exits 1 if a check fails
bench --site <site> demo-data uninstall [--run DD-RUN-00001] [--registry-only] [--no-backup] [--yes]
bench demo-data snapshot build --pack furniture_store [--size small]   # see Snapshots
bench demo-data snapshot new-site NAME DUMP.sql.gz [--admin-password PW]
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

## Banks and payments

The demo banks like a typical Indian SME, with two accounts of its own. It never
uses an account you already have:

| Bank Account | Ledger | Used for |
| --- | --- | --- |
| Current A/c (demo) - HDFC Bank | HDFC Bank Current A/c (demo) | Main account at the lender bank: supplier payments, NEFT/RTGS, cheque and UPI receipts from credit customers, the weekly transfers |
| Collection A/c (demo) - ICICI Bank | ICICI Bank Collection A/c (demo) | The showroom counter's UPI QR code and card terminal settle here |

If a name is taken, it becomes "... B", "... C", and so on. Account numbers and IFSC
codes are made up. Uninstall removes the accounts and ledgers. The *Bank* masters
("HDFC Bank", "ICICI Bank") are only the banks' names: existing ones are reused and
kept.

**Weekly transfers.** Every Monday, the collection account's balance is moved to the
main account (an Internal Transfer by NEFT), and the cash taken at the counter is
deposited into the main account. Only weeks with such receipts get a transfer. This
is a common pattern, and it matches the RBI rules for current accounts: a business
with bank loans of Rs 5 crore or more may keep only a *collection* account at a
bank that does not lend to it, and that account must pass its money on to the
lending bank promptly.

**Payment modes carry the receiving bank.** ERPNext links a *Mode of Payment* to one
account per company, and point-of-sale entries cannot pick another, so a business
receiving UPI or cards into more than one account names the modes after the
account: "UPI - ICICI" (counter QR), "Card - ICICI" (counter terminal), "UPI - HDFC"
(credit customers paying the invoice's bank details). Card networks (Visa,
Mastercard, RuPay) are not separate modes; the receiving bank is what matters. Cash,
Cheque and Wire Transfer are ERPNext's own modes and go to the main account. Modes
the site lacks are created, and removed on uninstall.

UPI receipts are sometimes entered as Wire Transfer with the UPI reference number;
separate modes keep them apart in reports. The UPI reference (the 12-digit RRN on
bank statements) goes in Reference No, so bank statement import and reconciliation
can match it. To collect UPI payments automatically (QR codes, payment links),
payment-gateway apps for Razorpay, PhonePe, PayU and others create these payment
entries for you; they are separate apps, not part of ERPNext or this demo.

How customers and suppliers pay (the mix is set per pack under `banking.modes`):

| Who | Methods |
| --- | --- |
| Showroom customers paying at the counter | Cash, UPI - ICICI, Card - ICICI |
| Credit customers (dealers, projects) | NEFT/RTGS, cheque, UPI - HDFC |
| The demo company paying suppliers | NEFT/RTGS, a few cheques and UPI - HDFC |

UPI is used up to Rs 1 lakh, for business customers too; larger payments go by
NEFT, or RTGS from Rs 2 lakh. Each bank payment carries a reference number like the
real one: a 12-digit RRN for UPI and cards, a NEFT or RTGS UTR, or a 6-digit cheque
number.

**Bank reconciliation.** The books are reconciled with both banks up to the end of
the month before the demo's end date: those payments have a clearance date (UPI the
same day, NEFT within a day, cards in one or two days, cheques in two to five).
Later payments are not cleared yet, so the *Bank Reconciliation Statement* and the
*Bank Reconciliation Tool* show realistic open items for each account.

Not modelled yet: card fees (MDR) and a card-settlement clearing account; card
payments reach the collection account directly, one or two days later.

## Sizes

Measured on a laptop (MariaDB in Docker); each submitted transaction takes about
0.3 to 0.4 s in ERPNext itself, so time grows with the number of documents:

| Pack | Micro (3 months) | Small (12 months) | Medium (24 months) |
| --- | --- | --- | --- |
| furniture_store | about 230 documents, 1 minute | about 1,000 documents, 4 minutes | about 18,000 documents, 1.5 hours |
| electrical_distributor | about 280 documents, 1.2 minutes | about 1,300 documents, 5.5 minutes | about 20,000 documents, about 1.5 hours (estimate) |

**Micro** is for quick tests and reproducing bugs, not for demos: few customers and
items, one quarter of data. It still covers every feature the demo has (quotations
won and lost, orders, deliveries, invoices paid, overdue, returned, cancelled and
left in draft, purchases, every payment mode, weekly bank transfers and bank
reconciliation): the planner checks this for every size and adjusts a few documents
when a small run would miss something.

## Reading the reports

- **Stock Balance shows fewer rows than the pack has items.** The report leaves out items
  with no stock in the chosen warehouses and dates. A demo ends with one or two
  fast-selling items sold out, as real shops do, so a Medium run with 250 stock items
  typically shows 248 or 249 rows. Tick the report's "Include Zero Stock Items" filter
  to see every item.

## Snapshots

A snapshot is a ready-made demo site: a database dump plus a manifest. Restoring
one takes about 15 seconds, against minutes or hours for a live install. A snapshot
site is disposable: explore it, then drop it with `bench drop-site`.

```bash
# build (on a throwaway site: setup wizard, install, verify, back up, drop)
bench demo-data snapshot build --pack furniture_store --size small \
      --db-root-password ... [--mariadb-user-host-login-scope '%']

# create a new site from it
bench demo-data snapshot new-site mydemo.localhost demo-snapshots/demo-furniture_store-small-...sql.gz \
      --admin-password ... --db-root-password ... [--mariadb-user-host-login-scope '%']
```

- Snapshots are written to `<bench>/demo-snapshots/`: `demo-<pack>-<size>-s<seed>-f<frappe>-e<erpnext>-ic<india_compliance>-dd<demo_data>-<date>.sql.gz`
  and a `.json` manifest beside it (pack, seed, data period, app versions and commits,
  document counts, checksum).
- The site has one company, the demo company, and one user, Administrator. Its
  password is **`changeme`** unless you set one with `--admin-password`. The data is
  fictional and open; dumps are not encrypted.
- `snapshot new-site` checks the checksum and versions first. A snapshot from an
  older release of the same major version is restored and then migrated. One from a
  newer release, or another major version, is refused: build a snapshot on this
  bench instead. It never touches an existing site.
- The dump is a standard Frappe backup, so Frappe's own commands work too:
  `bench new-site NAME --source-sql /absolute/path/to/dump.sql.gz` (the path must be
  absolute) or `bench --site NAME restore dump.sql.gz`. Frappe keeps the snapshot's
  Administrator password `changeme` on restore even when `--admin-password` is
  passed; change it with `bench --site NAME set-admin-password`.
- The data ends on the build date; the build date and data period are printed on
  restore.

`demo-data uninstall` with `--use-wizard-company` (demo data in your own company)
backs up the site first, as `bench drop-site` does; skip it with `--no-backup`.

## Development

```bash
bench --site demo-data.localhost run-tests --app demo_data       # unit tests (planner, packs, generators)
bench --site demo-data.localhost execute demo_data.tests.smoke.run \
      --kwargs '{"pack": "furniture_store", "seed": 11}'          # micro install, verify, uninstall, compare counts
# add "size": "small" (or "medium") to test a larger size
```

`dev/phase0_spike.py` is the Phase 0 runtime spike (see section 6.2 of the design).

## License

GPL-3.0
