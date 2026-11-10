# erpnext_demo_gen: Demo Generator for ERPNext

Fills an ERPNext site with realistic demo data. One command adds it; one command removes it.

## What it does

- Creates a demo company with months or years of business history.
- The history has quotations, orders, deliveries, invoices, payments, returns, stock
  and bank transfers, plus the company's own office supplies.
- Each country gets its own tax set-up, chart of accounts, addresses, banks and names.
- `verify` checks the result: ledgers balance, reports match invoices, tax is right.
- `uninstall` removes everything the demo created. Your own data stays.
- The same options give the same data, on any site.

Countries and packs (a pack is a type of business):

```
India                    furniture_store, electrical_distributor
United States            furniture_store
UAE                      furniture_store
Germany                  furniture_store
```

## Requirements

- frappe and erpnext, version 16 or later.
- The setup wizard is finished, for the demo's country and currency.
  For example, a German demo needs a site set up for Germany, in EUR.
- The Redis queue is running (`bench start`). Uninstall needs it.
- India only: the india_compliance app.

## Installation

The examples in this README use a site called `demo.localhost`.

```bash
bench get-app https://github.com/thava/erpnext_demo_gen
bench --site demo.localhost install-app erpnext_demo_gen
```

## Command summary

A quick reference. The [tutorial](#tutorial) below explains each option with examples.

```bash
bench --site <site> demo-gen list-packs
bench --site <site> demo-gen install --country IN|US|AE|DE [--pack NAME] [--size micro|small|medium]
      [--seed N] [--end-date YYYY-MM-DD] [--home-state STATE] [--demo-company-name NAME]
      [--use-wizard-company] [--no-gst | --fictitious-gstin] [--force] [--verbose]
bench --site <site> demo-gen status
bench --site <site> demo-gen history [--run DD-RUN-00001] [--limit 20]
bench --site <site> demo-gen verify [--run DD-RUN-00001]
bench --site <site> demo-gen uninstall [--run DD-RUN-00001] [--yes] [--registry-only] [--no-backup]
bench demo-gen snapshot build --country IN|US|AE|DE [--pack NAME] [--size small] [--seed N]
bench demo-gen snapshot new-site NAME DUMP.sql.gz [--admin-password PW]
```

## Tutorial

### Install, check, remove

Install an Indian demo:

```bash
bench --site demo.localhost demo-gen install --country IN
```

The output looks like this (shortened):

```
Pack: furniture_store (its default pack), country: India (IN), currency INR
Started DD-RUN-00009
Setting up the company, warehouses, fiscal years and bank accounts...
Company: Indigo Brass Home Studio Pvt Ltd
Plan: 1196 documents
Writing them takes about 4 min; please wait. Progress is shown every 20 s. ...
  201 of 1196 documents written (16%), 20 s so far, about 2 min left
  ...
DD-RUN-00009 completed: 1210 documents in Indigo Brass Home Studio Pvt Ltd after 5 min
Check it with: demo-gen verify. Remove it with: demo-gen uninstall.
```

- `--country` is the only required option.
- Each install is a *run* with its own number (`DD-RUN-00009`).
- The run creates a new company. Its name is made up (here "Indigo Brass Home Studio Pvt Ltd").
- The size is `small` by default: 12 months of data, about 1,200 documents.

Check the result:

```bash
bench --site demo.localhost demo-gen verify
```

```
DD-RUN-00009 (Indigo Brass Home Studio Pvt Ltd)
  ok   trial balance balances: debit - credit = 0.00
  ok   receivable aging matches outstanding: report 1,886,615.00, invoices 1,886,615.00, ...
  ok   no negative stock: 0 ledger rows below zero
  ok   taxable documents have GST rows: all present
  ok   payments use every planned mode: Card - ICICI: 16, Cash: 31, Cheque: 27, ...
  ...
19/19 checks passed
```

- `verify` exits with code 1 if any check fails, so scripts and CI can use it.
- The checks depend on the country. For example, Germany adds VAT checks.

Remove it:

```bash
bench --site demo.localhost demo-gen uninstall
```

```
Delete demo data of DD-RUN-00009 (Indigo Brass Home Studio Pvt Ltd)? [y/N]: y
Deleting transactions of Indigo Brass Home Studio Pvt Ltd (Transaction Deletion Record)
Deleting the demo's customers, suppliers, items and other setup records...
DD-RUN-00009 uninstalled after 29 s
```

- Uninstall deletes the whole demo company.
- That includes anything you added to the demo company yourself while exploring.
- Add `--yes` to skip the question (useful in scripts).

### See what is installed

```bash
bench --site demo.localhost demo-gen status
```

```
DD-RUN-00009  Completed: furniture_store (IN)/small seed 1, data up to 2026-11-11, company Indigo Brass Home Studio Pvt Ltd
    1210 documents; since 2026-11-11 04:40
Runs on this site: 9 (1 completed, 8 uninstalled). Details: demo-gen history
```

```bash
bench --site demo.localhost demo-gen history --limit 4
```

```
2026-11-11 04:40  DD-RUN-00009  installed after 5 min (Created 187, Submitted 1023)
2026-11-11 04:36  DD-RUN-00009  install started: furniture_store (IN)/small seed 1, ...
2026-11-10 04:25  DD-RUN-00008  uninstalled after 17 s (Deleted 286)
2026-11-10 04:24  DD-RUN-00008  uninstall started
... 30 older events (--limit)
```

```bash
bench --site demo.localhost demo-gen history --run DD-RUN-00009   # one run, with counts per doctype
```

### Choose the country

`--country` takes a code or a name. Case, spaces and hyphens do not matter.

```bash
bench --site demo.localhost demo-gen install --country IN          # or india
bench --site demo.localhost demo-gen install --country US          # or USA, "United States", united-states
bench --site demo.localhost demo-gen install --country AE          # or UAE, united-arab-emirates
bench --site demo.localhost demo-gen install --country Germany     # or DE, Deutschland
```

- There is no default country. The country decides the tax rules, so you always choose it.
- The site's setup wizard must match: an Indian site for `IN`, a German site for `DE`.

### Choose the pack

List the packs:

```bash
bench --site demo.localhost demo-gen list-packs
```

```
Pack                     Countries       Sizes                  Title
electrical_distributor   IN              micro, small, medium   Electrical Equipment Distributor
furniture_store          AE, DE, IN, US  micro, small, medium   Furniture Store; ...
Default pack per country: AE furniture_store, DE furniture_store, IN furniture_store, US furniture_store
```

```bash
bench --site demo.localhost demo-gen install --country IN --pack electrical_distributor
bench --site demo.localhost demo-gen install --country IN      # furniture_store, the default for India
```

- `--pack` is optional. Each country has a default pack.
- One pack can exist in several countries. The country is not part of the pack name.

### Choose the size

```bash
bench --site demo.localhost demo-gen install --country US --size micro    # 3 months, about 300 documents, 1 minute
bench --site demo.localhost demo-gen install --country US                 # small: 12 months, about 1,200 documents, 5 minutes
bench --site demo.localhost demo-gen install --country US --size medium   # 24 months, about 19,000 documents, 1 to 2 hours
```

- `micro` is for quick tests and bug reports. It still has every kind of document
  the demo makes, but few customers and items.
- `small` is the default and suits most demos.
- `medium` looks like a real business, but takes an hour or more.
  Use a [snapshot](#snapshots) to build it once and restore it in seconds.
- Times for every pack are under [Sizes](#sizes).

### Get the same data again, or different data

```bash
bench --site demo.localhost demo-gen install --country IN --seed 7
```

- The seed picks the names, items, customers and amounts. The default is 1.
- The same seed, options and `--end-date` give the same data on any site.
  Without `--end-date`, the data ends today, so dates shift from day to day.
- A different seed gives a different company with different data.

```bash
bench --site demo.localhost demo-gen install --country IN --end-date 2026-03-31
```

- Data ends on `--end-date`. The default is today.
- `2026-03-31` ends the data at the close of India's fiscal year.

### Name the demo company

```bash
bench --site demo.localhost demo-gen install --country US --demo-company-name "Lone Star Furniture Inc"
# Creates the company "Lone Star Furniture Inc" and makes it the default company.
# It is registered as ERPNext's demo company, so the desk's
# "Delete Demo Data" button removes it, the same way uninstall does.

bench --site demo.localhost demo-gen uninstall --yes
# Deletes "Lone Star Furniture Inc" and restores the default company you had before.
```

- Without `--demo-company-name`, the name is made up from the seed.

### Choose the home state

The demo company's address is in the pack's home state. Change it with `--home-state`:

```bash
bench --site demo.localhost demo-gen install --country IN --home-state KA         # Karnataka (default: Tamil Nadu)
bench --site demo.localhost demo-gen install --country IN --home-state 29         # the same, by GST state code
bench --site demo.localhost demo-gen install --country AE --home-state SH         # Sharjah (default: Dubai)
bench --site demo.localhost demo-gen install --country DE --home-state HH         # Hamburg (default: Bayern)
```

- India: a state name, a code (TN, KA) or a GST state code (33).
- UAE: an emirate (DU, AZ, SH, AJ, RK, FU, UQ) or its name.
- Germany: a Bundesland (BY, BE, HH, NW, BW, HE, NI, SN, RP, SH) or its name.
- US: only TX.
- Most customers are in the home state; suppliers are spread wider, as for a real business.

### A site that is already in use

If the site already has transactions, install stops and explains:

```bash
bench --site demo.localhost demo-gen install --country IN
```

```
This site already has transactions:
  Kaveri Traders (default company): 42 documents, 180 GL entries
The demo goes into a new, separate company (a peer, not a child company) and
does not change these. It becomes the default company while installed;
uninstall deletes it and restores the current default.
This is safe, but because the site is in use, installing needs --force.
```

```bash
bench --site demo.localhost demo-gen install --country IN --force
```

- `--force` is also needed when the GST API is on (India), or with `--no-gst`.

### Stop and resume

```bash
bench --site demo.localhost demo-gen install --country US --size medium
# ... press Ctrl+C, or the machine restarts ...
bench --site demo.localhost demo-gen install --country US --size medium
# The same command resumes where it stopped.
```

### See every document created

```bash
bench --site demo.localhost demo-gen install --country AE --verbose
# At the end, prints how many documents of each doctype were created.
```

Every document is also recorded in the *Demo Data Record* list, under its *Demo Data Run*.
Uninstall uses that record, together with ERPNext's Transaction Deletion Record.

### Remove one run of several

```bash
bench --site demo.localhost demo-gen uninstall --run DD-RUN-00009
```

- Without `--run`, uninstall removes the only active run.
- `verify --run DD-RUN-00009` checks one run the same way.

### Put the demo into your own company

By default the demo gets a new company. `--use-wizard-company` uses the company
made by the setup wizard instead:

```bash
bench --site demo.localhost demo-gen install --country DE --use-wizard-company
# Adds the demo's documents to your default company.
# --force is needed only if that company already has transactions.

bench --site demo.localhost demo-gen uninstall
# Backs up the site first, as bench drop-site does.
# Then removes only the demo's documents, one by one.
# Keeps (and lists) any demo document that your own documents refer to.
```

```bash
bench --site demo.localhost demo-gen uninstall --no-backup     # skip the backup
```

Country notes:

- Germany: the company must use the SKR04 chart (*SKR04 mit Kontonummern*).
- India: the company needs a GSTIN. If its company address has one, its GST state
  becomes the home state. If not, pick one of these:

```bash
bench --site demo.localhost demo-gen install --country IN --use-wizard-company --fictitious-gstin
# Adds a company address with a made-up GSTIN. Uninstall removes it.

bench --site demo.localhost demo-gen install --country IN --use-wizard-company --no-gst --force
# Treats the company as not registered for GST. See "Unregistered businesses" below.
```

The one-by-one removal also works for a demo company:

```bash
bench --site demo.localhost demo-gen uninstall --registry-only
```

## Countries

All tax notes below are general information, not tax advice.

### India

```bash
bench --site demo.localhost demo-gen install --country IN                                  # furniture showroom
bench --site demo.localhost demo-gen install --country IN --pack electrical_distributor    # electrical wholesaler
```

- The demo company is in Tamil Nadu, as an example. Pick another state with `--home-state`.
- GST through india_compliance: CGST and SGST in the home state, IGST across states.
- Each item's GST rate comes from its Item Tax Template.
- Two demo bank accounts, UPI and card receipts, weekly transfers.
  See [Banks and payments](#banks-and-payments).
- Unregistered businesses are supported with `--no-gst`. See the next section.

### Unregistered businesses (no GST)

Many small Indian businesses are not registered for GST. This demo can show one:

```bash
bench --site demo.localhost demo-gen install --country IN --no-gst --force
```

ERPNext and india_compliance do not handle this case by themselves.
The demo does the set-up that such a business has to do by hand:

- With no GSTIN, india_compliance turns off all its GST logic.
- Sales carry no GST. That is right: an unregistered business does not charge it.
- Purchases from GST-registered suppliers **still include GST**.
- The business cannot claim that GST back (no input tax credit).
  So the GST is part of what the goods cost.
- ERPNext does not add it by default. Without the set-up below, the purchase
  has no GST, and the amount owed to the supplier is too low.

**Set-up: two purchase templates without ITC.** The demo creates these.
A real unregistered company needs the same:

| Template | Rows |
| --- | --- |
| Input GST In-state (no ITC) | CGST and SGST, as in "Input GST In-state" |
| Input GST Out-state (no ITC) | IGST, as in "Input GST Out-state" |

To make one by hand:

1. Open *Purchase Taxes and Charges Template*.
2. Duplicate your company's "Input GST In-state" (or "Out-state") template, and rename it.
3. In every row, set **Consider Tax or Charge for** to **Valuation and Total** (Add or Deduct: Add).
4. Leave Tax Category empty.

"Valuation and Total" adds the GST to the item's valuation rate.
So stock value and cost of goods sold include it.
Each item's GST rate still comes from its Item Tax Template.

**Using the templates:**

- On a purchase order or invoice from a GST-registered supplier, pick a template:
  in-state if the supplier is in your state, out-state otherwise.
- Receipts and invoices made from the order copy the tax rows.
- Purchases from unregistered suppliers get no template.

**Letting ERPNext pick the template.** Add two *Tax Rules* (Tax Type: Purchase, your company):

```
rule 1    Billing State = your state    template: Input GST In-state (no ITC)
rule 2    no state                      template: Input GST Out-state (no ITC)
# the more specific rule wins, so in-state suppliers get rule 1
```

- A rule matches only suppliers with the same Tax Category (empty matches empty).
- Give unregistered suppliers a Tax Category such as "Unregistered". Then no rule applies to them.
- Do not just mark a template as the default. It would add GST to purchases from
  unregistered suppliers too.

**Other rules the demo follows:**

- **Customers only in your state.** An unregistered business cannot sell to another
  state, or to an SEZ: that needs GST registration at any turnover.
  The demo uses Tamil Nadu as the home state, as an example, and puts every customer
  in Tamil Nadu. With `--home-state KA`, every customer is in Karnataka instead.
  Suppliers can be anywhere.
- **Turnover above the threshold.** The demo uses the pack's normal volume. That is above
  the registration threshold (Rs 40 lakh a year for goods; Rs 20 lakh in special-category
  states). Install prints a warning: a real business that size must register.
- **Your own company.** With `--use-wizard-company --no-gst`, the two templates are
  created in your company. Uninstall removes them, unless your own documents use them;
  those are kept and listed. To keep using them after uninstall, make your own copies.
- `verify` checks that sales carry no GST, and that purchases from registered
  suppliers carry GST rows marked "Valuation and Total".

### United States

```bash
bench --site demo.localhost demo-gen install --country US
```

- A Texas furniture showroom, with a trade channel (designers and projects).
- Texas is an example, chosen because its sales tax is simple for a business that
  sells only in its own state: one combined rate for every sale.
- Selling into other states, with each state's own rules, is not part of the demo.
  A real business doing that usually needs a tax service app (TaxJar, Avalara).
- The demo sells only in Texas, so every sale is taxed at 8.25%.
  That is 6.25% state tax plus the 2% local maximum (Austin: 1% city, 1% transit).
- The rate is fixed in the pack (`sales_tax` in `us_trading.yaml`). It is never fetched
  from a tax service.

What the install sets up:

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

- Reseller customers have a Texas resale certificate number and buy tax-free.
- Out-of-state suppliers have the "Out of State" tax category.
- ERPNext's own US templates (US ST 6% and others) stay, but are no longer the defaults.
- Payments: Check, ACH, Wire Transfer and Card. Account and routing numbers are made up.
- The fiscal year runs January to December.
- `--no-gst` and `--fictitious-gstin` do not apply. `--home-state` accepts only TX.

### United Arab Emirates

```bash
bench --site demo.localhost demo-gen install --country AE
```

- A VAT-registered furniture showroom in Dubai (an example; `--home-state` picks another
  emirate), with a trade channel (fit-out, hospitality, projects).
- It uses ERPNext's own UAE set-up.

```
VAT             5% on sales and purchases ("UAE VAT 5%", made the default templates),
                with input credit; shelf prices include VAT (UAE consumer rules)
VAT Emirate     each sale's VAT Emirate (VAT 201 boxes 1a-1g) comes from the company
                address's Emirate field, which the install sets to Dubai
recoverable     every purchase bill records its VAT as "Recoverable Standard Rated
                Expenses" (VAT 201 box 9)
UAE VAT Settings  lists the company's VAT account (reverse charge and VAT 201 use it)
parties         TRNs (15 digits) for VAT-registered businesses; emirates as states,
                P.O. Boxes, +971 numbers
banking         Emirates NBD and Mashreq accounts with valid-format IBANs; wire
                transfer, cheque, card (collection account) and cash; AED
```

- `verify` runs ERPNext's UAE VAT 201 report. It checks that boxes 1 and 9 match the invoices.
- Not covered: imports and reverse charge, zero-rated exports, tourist refunds,
  excise, designated zones.

### Germany

```bash
bench --site demo.localhost demo-gen install --country DE
```

- A VAT-registered furniture store (GmbH) in Munich (an example; `--home-state` picks
  another Bundesland), with a trade channel (interior designers, hotels, office fit-out).
- It uses the SKR04 chart and ERPNext's own German tax set-up.

```
chart           SKR04 mit Kontonummern; ERPNext creates its tax templates with the company
VAT             sales "Lieferung oder sonstige Leistung im Inland", purchases "Lieferung
                aus dem Inland": rows for 19 % and 7 % at rate 0; each item's Item Tax
                Template ("19 %", "7 %") sets the rate, so one invoice can mix both
rates           furniture 19 %; staff coffee 7 % (food); bottled water 19 %
prices          shop prices include VAT (Preisangabenverordnung)
defaults        income, receivable, payable, cash and expense defaults set to the usual
                SKR04 ledgers (4400, 1200, 3300, 1600, 5200) where ERPNext picked others
parties         USt-IdNr. (valid check digit) for VAT-registered businesses; Bundesländer,
                5-digit postcodes, +49 numbers
banking         Stadtsparkasse München and Deutsche Bank accounts with valid-format IBANs;
                SEPA transfer, SEPA direct debit, card (collection account) and cash; EUR
```

- `verify` checks that each invoice's VAT matches its items' rates.
- It checks that the 7 % items are billed at 7 %.
- It checks that the VAT accounts match the invoices (the UStVA totals:
  output VAT, input VAT, payable).
- The install fills each order's tax rows itself. So ERPNext's setting "Automatically add
  Taxes and Charges from Item Tax Template" (on by default) can stay on.
- `--use-wizard-company` needs a company on the SKR04 chart.
- Not covered: EU and non-EU trade (reverse charge), Kleinunternehmer suppliers,
  DATEV export, e-invoicing (XRechnung, ZUGFeRD).

## Own-use supplies

Every pack also buys supplies for its own use, as any business does:

- Copier paper, toner, pens, registers, cleaning supplies, tea or coffee.
- They are counted in their own warehouse ("Office Stores"), with reorder levels.
- Drinking water is billed monthly.

Each month:

1. A department raises a Material Request (Material Issue).
2. A Stock Entry issues the supplies.
3. The cost goes to Print and Stationery, or Office Maintenance Expenses.

When an item reaches its reorder level:

1. A purchase Material Request follows the next day, as ERPNext's daily reorder job would raise it.
2. Then come the purchase order, the receipt and the bill.

The reorder job itself does not run during an install. To see it work afterwards, turn on
"Raise Material Request when stock reaches re-order level" in Stock Settings.

## Banks and payments

Every demo company gets two bank accounts of its own, in every country:

- a **main account**, at the bank that lends to the company;
- a **collection account**, where the shop's card terminal (and in India, the UPI QR code) settles.

The banks per country:

```
India            main: HDFC Bank                collection: ICICI Bank
United States    main: Frost Bank               collection: Wells Fargo Bank
UAE              main: Emirates NBD             collection: Mashreq Bank
Germany          main: Stadtsparkasse München   collection: Deutsche Bank
```

For example, the German demo creates:

```
Current A/c (demo) - Stadtsparkasse München      # main account
    ledger: Stadtsparkasse München Current A/c (demo)
Collection A/c (demo) - Deutsche Bank            # collection account
    ledger: Deutsche Bank Collection A/c (demo)
```

- The bank names are real. Account numbers are made up, but in the right format
  (IFSC in India, routing numbers in the US, IBANs in the UAE and Germany).
- If the site already has bank accounts, the demo never reuses them. It always creates its own.
- If a name is taken, the new one becomes "... B", "... C", and so on.
- Uninstall removes the demo's bank accounts and ledgers.
- Each bank account links to a *Bank* record, which holds just the bank's name
  (for example "Deutsche Bank"). The demo creates the record if the site has none,
  and uninstall removes it. If the site already has one, the demo links to it
  and uninstall leaves it in place.

**Weekly transfers.** Every Monday:

- The collection account's balance moves to the main account (an Internal Transfer).
- Cash taken at the counter is deposited into the main account.
- Weeks with no such receipts get no transfer.

**Payment modes.** Card payments use a mode named after the collection bank, such as
"Card - DB" in Germany. ERPNext links a *Mode of Payment* to one account per company,
and point-of-sale entries cannot pick another, so naming the mode after the account is
how a business receives payments into two accounts.

How customers and suppliers pay, per country (set per pack under `banking.modes`):

```
India            counter: Cash, UPI, Card       customers: NEFT/RTGS, cheque, UPI
                 suppliers: NEFT/RTGS, a few cheques and UPI
United States    counter: Cash, Card            customers and suppliers: ACH, Check, Wire Transfer
UAE              counter: Cash, Card            customers and suppliers: Wire Transfer, Cheque
Germany          counter: Cash, Card            customers and suppliers: SEPA transfer, SEPA direct debit
```

- Modes the site lacks are created, and removed on uninstall.
- Each bank payment has a realistic reference number (for example a cheque number).

**Bank reconciliation.**

- Both accounts are reconciled up to the end of the month before the demo's end date.
- Those payments have a clearance date, a few days after the payment,
  depending on the mode. For example, in India: UPI the same day, NEFT within a day,
  cards in one or two days, cheques in two to five.
- Later payments are not cleared yet. So the *Bank Reconciliation Statement* and
  *Bank Reconciliation Tool* show realistic open items for each account.
- Not modelled yet: card fees and a card-settlement clearing account.
  Card payments reach the collection account directly, one or two days later.

### India: UPI and the RBI rule

- The showroom has a UPI QR code and a card terminal. Both settle into the ICICI collection account.
- Credit customers also pay by UPI, to the bank details on the invoice (the HDFC main account).
- So India has three named modes:

```
UPI - ICICI     counter QR code
Card - ICICI    counter card terminal
UPI - HDFC      credit customers paying to the invoice's bank details
Cash, Cheque, Wire Transfer    ERPNext's own modes; go to the main account
```

- Card networks (Visa, Mastercard, RuPay) are not separate modes. The receiving bank is what matters.
- UPI receipts are sometimes entered as Wire Transfer. Separate modes keep them apart in reports.
- UPI is used up to Rs 1 lakh, by business customers too.
  Larger payments go by NEFT, or RTGS from Rs 2 lakh.
- References: a 12-digit RRN for UPI and cards, a NEFT or RTGS UTR, or a 6-digit cheque number.
- The UPI reference (the RRN on bank statements) goes in Reference No.
  Bank statement import and reconciliation can then match it.
- Payment-gateway apps (Razorpay, PhonePe, PayU and others) can create these payment
  entries automatically. They are separate apps, not part of ERPNext or this demo.

Why two banks? The weekly transfer is a common pattern. It also matches RBI rules:
a business with bank loans of Rs 5 crore or more may keep only a *collection* account
at a bank that does not lend to it, and that account must pass its money on to the
lending bank promptly.

## Sizes

Measured on a laptop (MariaDB in Docker). ERPNext takes about 0.3 to 0.4 s to submit
each document, so time grows with the number of documents.

```
furniture_store (IN)       micro   ~290 docs, 1.2 min    small  ~1,200 docs, 5 min    medium  ~18,500 docs, 1.5 h
electrical_distributor     micro   ~320 docs, 1.4 min    small  ~1,500 docs, 6 min    medium  ~23,300 docs, 2 to 2.5 h
furniture_store (US)       micro   ~300 docs, 1 min      small  ~1,200 docs, 5 min    medium  ~19,000 docs, 1.7 h
furniture_store (AE)       micro   ~300 docs, 1 min      small  ~1,200 docs, 5 min    medium  ~18,900 docs, 1 h (CI)
furniture_store (DE)       micro   ~310 docs, 1 min      small  ~1,200 docs, 4 min    medium  ~19,400 docs, 1 h (CI)
```

- micro: 3 months; small: 12 months; medium: 24 months.
- Every size covers every kind of document: quotations won and lost, orders, deliveries,
  invoices paid, overdue, returned, cancelled and left in draft, purchases, every payment
  mode, weekly bank transfers and bank reconciliation.
- The planner checks this for every size. It adjusts a few documents when a small run
  would miss something.

## Reading the reports

- **Stock Balance shows fewer rows than the pack has items.** The report leaves out
  items with no stock. A demo ends with one or two fast sellers sold out, as in real
  shops. So a Medium run with 250 stock items usually shows 248 or 249 rows.
  Tick "Include Zero Stock Items" to see them all.

## Snapshots

A snapshot is a ready-made demo site: a database dump plus a manifest.

- Restoring one takes about 15 seconds. A live install takes minutes or hours.
- A snapshot site is disposable: explore it, then drop it with `bench drop-site`.
- Snapshot commands need no `--site`. They create their own sites.

Build a snapshot:

```bash
bench demo-gen snapshot build --country DE --size medium
# Creates a throwaway site, runs the setup wizard, installs, verifies, backs up, drops the site.
# Asks for the MariaDB root password (or pass --db-root-password).
# Add --mariadb-user-host-login-scope '%' when MariaDB runs in Docker.
```

```
Snapshot ready: demo-snapshots/demo-furniture_store-DE-medium-s1-f16.56.0-e16.54.0-dd0.0.1-20261110.sql.gz (and its .json manifest)
```

- The file name holds the pack, country, size, seed, app versions and build date.
  India snapshots also hold the india_compliance version (`ic...`).
- The `.json` manifest beside it lists the pack, seed, data period, app versions
  and commits, document counts and a checksum.
- `--out DIR` writes the snapshot somewhere other than `<bench>/demo-snapshots/`.

Make a new site from it:

```bash
bench demo-gen snapshot new-site berlin.localhost \
      demo-snapshots/demo-furniture_store-DE-medium-s1-f16.56.0-e16.54.0-dd0.0.1-20261110.sql.gz \
      --admin-password secret
# Checks the checksum and versions, then creates berlin.localhost from the dump.
# Prints the build date and the data period. The data ends on the build date.
```

- The site has one company (the demo company) and one user, Administrator.
- The password is **`changeme`** unless you set one with `--admin-password`.
- The data is fictional and open. Dumps are not encrypted.
- A snapshot from an older release of the same major version is restored, then migrated.
- One from a newer release, or another major version, is refused. Build one on this bench instead.
- `new-site` never touches an existing site.

The dump is a standard Frappe backup, so Frappe's own commands also work:

```bash
bench new-site berlin.localhost --source-sql /absolute/path/to/dump.sql.gz    # the path must be absolute
bench --site berlin.localhost restore dump.sql.gz
bench --site berlin.localhost set-admin-password secret
# Frappe keeps the snapshot's password "changeme" on restore, even with --admin-password,
# so set it afterwards.
```

## Development

```bash
bench --site demo-data.localhost run-tests --app erpnext_demo_gen
# unit tests: planner, packs, generators

bench --site demo-data.localhost execute erpnext_demo_gen.tests.smoke.run \
      --kwargs '{"country": "IN", "pack": "furniture_store", "seed": 11}'
# micro install, verify, uninstall, then compare document counts
# add "size": "small" (or "medium") to test a larger size
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports, questions and ideas are welcome as
issues. Pull requests are not accepted for now.

## License

Copyright (C) 2026 Thava Alagu.

This program is free software: you can redistribute it and/or modify it under the terms
of the GNU General Public License version 3, as published by the Free Software
Foundation. See [license.txt](license.txt).

ERPNext and Frappe are trademarks of Frappe Technologies Pvt. Ltd. This project is
independent and is not affiliated with or endorsed by Frappe Technologies.
