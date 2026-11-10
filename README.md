# Demo Data

Realistic, removable demo data for ERPNext v16+, for India, the United States (Texas) and the United Arab Emirates (Dubai).

Status: Phase 2. `install` creates a demo company with its country's set-up, masters
and a quarter (Micro), a year (Small) or two (Medium) of purchases, sales, payments,
returns, open items and own-use supplies; `verify` checks the result; `uninstall`
removes it. Packs: `furniture_store` (India, US, UAE) and `electrical_distributor`
(India). The requirements and design live in the bench folder:
`demo-data-req-design.md`.

## Requirements

frappe and erpnext v16+, a finished setup wizard in the pack's country and currency,
and a running Redis queue (ERPNext's Transaction Deletion Record needs it). India
packs also need india_compliance.

## Usage

```bash
bench --site <site> demo-data list-packs                      # packs, their countries and sizes
bench --site <site> demo-data install --country IN|US|AE [--pack furniture_store] [--size micro|small|medium] \
      [--seed N] [--end-date YYYY-MM-DD] [--home-state TN] [--demo-company-name NAME] [--use-wizard-company]
      [--no-gst | --fictitious-gstin] [--force]
bench --site <site> demo-data status                          # what is installed now
bench --site <site> demo-data history [--run DD-RUN-00001]     # install/uninstall events, newest first
bench --site <site> demo-data verify [--run DD-RUN-00001]      # exits 1 if a check fails
bench --site <site> demo-data uninstall [--run DD-RUN-00001] [--registry-only] [--no-backup] [--yes]
bench demo-data snapshot build --country IN|US|AE [--pack furniture_store] [--size small]   # see Snapshots
bench demo-data snapshot new-site NAME DUMP.sql.gz [--admin-password PW]
```

- `--country` is required for `install` and `snapshot build`: there is no default, so
  the country is always a deliberate choice. It takes a code or a name, ignoring case,
  spaces and hyphens (`IN`, `india`, `US`, `USA`, `"United States"`, `united-states`,
  `AE`, `UAE`, `united-arab-emirates`).
  `--pack` is optional: each country has a default pack (`list-packs` shows them).
  A pack can exist for several countries (`furniture_store` is IN and US); the country
  is never part of the pack name.
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

## United States (Texas)

`--country US` (pack `furniture_store`) is a Texas furniture showroom with a trade channel (designers and
projects). It sells only in Texas, so one combined sales tax rate applies to every sale:
Texas taxes in-state sales at the seller's location, and a store in a city at the 2%
local maximum charges 8.25% (6.25% state + 2% local; Austin: 1% city + 1% transit).
The rate is fixed pack data (`sales_tax` in `us_trading.yaml`), never fetched from a
tax service; real US businesses usually use one (TaxJar, Avalara), especially when
they sell into other states. General information, not tax advice.

What the install sets up for the demo company:

```
accounts        Texas Sales Tax Payable, Texas Use Tax Payable (Duties and Taxes)
                Sales Tax Paid, Use Tax Expense (Indirect Expenses)
sales           "TX Sales Tax 8.25%" (default); "TX Exempt Sale" for resellers
purchases       "TX Resale Purchase (certificate)": stock for resale, no tax
                "TX Tax Charged 8.25%" (default): own-use bills from Texas sellers
                "TX Use Tax 8.25%": own-use bills from out-of-state sellers; adds the tax
                to expense and owes it to Texas (Add and Deduct rows)
items           "TX Exempt - Food" Item Tax Template (coffee, bottled water)
categories      Tax Categories "Reseller" and "Out of State", with Tax Rules, so
                documents you create by hand pick the same templates
```

Reseller customers carry their Texas resale certificate number in their details and
buy tax-free; out-of-state suppliers carry the "Out of State" category. ERPNext's own US
templates (US ST 6% and so on) stay but are no longer the defaults. Payments use Check,
ACH, Wire Transfer and Card (into the collection account), at made-up account and
routing numbers; the fiscal year runs January to December.

`--no-gst`, `--fictitious-gstin` and India states are not available with US packs;
`--home-state` accepts only TX.

## United Arab Emirates (Dubai)

`--country AE` (pack `furniture_store`) is a VAT-registered Dubai furniture showroom with a
trade channel (fit-out, hospitality, projects), using ERPNext's own UAE set-up:

```
VAT             5% on sales and purchases ("UAE VAT 5%", made the default templates),
                with input credit; shelf prices include VAT (UAE consumer rules)
VAT Emirate     each sale's VAT Emirate (VAT 201 boxes 1a-1g) is fetched from the
                company address's Emirate field, which the install sets to Dubai
recoverable     every purchase bill records its VAT as "Recoverable Standard Rated
                Expenses" (VAT 201 box 9)
UAE VAT Settings  lists the company's VAT account (reverse charge and VAT 201 use it)
parties         TRNs (15 digits) for VAT-registered businesses; emirates as states,
                P.O. Boxes, +971 numbers
banking         Emirates NBD and Mashreq accounts with valid-format IBANs; wire
                transfer, cheque, card (collection account) and cash; AED
```

`verify` runs ERPNext's UAE VAT 201 report and checks that boxes 1 and 9 match the
invoices. Out of scope: imports and reverse charge, zero-rated exports, tourist refunds,
excise, designated zones. `--home-state` takes an emirate (DU, AZ, SH, AJ, RK, FU, UQ or
the name). General information, not tax advice.

## Own-use supplies

Every pack also keeps supplies for its own use, as any business does: copier paper,
toner, pens, registers, cleaning supplies, tea or coffee, counted in their own
warehouse ("Office Stores") with reorder levels, plus drinking water billed monthly.
Each month departments raise a Material Request (Material Issue) and a Stock Entry
issues it; the cost goes to Print and Stationery or Office Maintenance Expenses when
issued. When an item reaches its reorder level, a purchase Material Request follows the
next day, as ERPNext's daily reorder job would raise it (the job itself does not run
during an install; turn on "Raise Material Request when stock reaches re-order level"
in Stock Settings to see it work afterwards), then the order, receipt and bill.

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
| furniture_store | about 290 documents, 1.2 minutes | about 1,200 documents, 5 minutes | about 18,500 documents, 1.5 hours |
| electrical_distributor | about 320 documents, 1.4 minutes | about 1,500 documents, 6 minutes | about 23,300 documents, 2 to 2.5 hours |
| furniture_store (US) | about 300 documents, 1 minute | about 1,200 documents, 5 minutes | about 19,000 documents, 1.7 hours |
| furniture_store (AE) | about 300 documents, 1 minute | about 1,200 documents, 5 minutes | about 19,000 documents (planned) |

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
bench demo-data snapshot build --country IN --pack furniture_store --size small \
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
