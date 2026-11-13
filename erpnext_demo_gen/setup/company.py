"""Demo company set-up (milestone 1). Country specifics come from the pack's locale.

Creates, through the registry: the demo Company (ERPNext installs the country's
fixtures; in India india_compliance adds GST accounts and tax templates, F-5), its
own Address with its tax ID (India: GSTIN; none with --unregistered; in wizard mode
added with a made-up GSTIN), the pack's warehouses and every Fiscal Year the date
range touches. Then makes the demo company the default, remembering the previous
default for uninstall. It is not registered as ERPNext's demo company (DEC-34).
"""

import random
from datetime import date

import frappe
from frappe.utils import add_days, add_months, getdate

from erpnext_demo_gen import naming
from erpnext_demo_gen.locales import get_locale
from erpnext_demo_gen.registry import Run
from erpnext_demo_gen.setup.tax_templates import purge_orphans

DEMO_LABEL = "Fictional company created by the erpnext_demo_gen app. All names, tax IDs and figures are made up."


def rng_for(run: Run, purpose: str) -> random.Random:
	"""A deterministic random stream per purpose, so adding one stream never shifts another."""
	return random.Random(f"{run.params.seed}:{purpose}")


def date_range(end_date: date, months: int) -> tuple[date, date]:
	return add_days(add_months(end_date, -months), 1), end_date


def fiscal_year_starts(start: date, end: date, locale=None) -> list[date]:
	"""Fiscal years that the range touches (the locale's; India: April to March)."""
	return (locale or get_locale()).fiscal_year_starts(start, end)


def choose_company_name(run: Run, pack: dict) -> str:
	if run.params.get("company"):
		return run.params.company
	rng = rng_for(run, "company-name")
	for _ in range(50):
		name = get_locale(pack).company_name(rng, pack["company"]["industry_nouns"])
		if not frappe.db.exists("Company", name):
			return name
	frappe.throw("Could not find an unused company name; pass --demo-company-name")


def setup_company(run: Run, pack: dict) -> str:
	params = run.params
	home_state = params.home_state
	locale = get_locale(pack)

	if params.use_wizard_company:
		company = params.company
	else:
		company_name = choose_company_name(run, pack)
		run.set_company(company_name)

		def create_company():
			taken = set(frappe.get_all("Company", pluck="abbr"))
			abbr = naming.abbreviation(company_name, taken)
			purge_orphans(abbr)  # F-26
			return frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": company_name,
					"abbr": abbr,
					**locale.company_fields(params),
					"company_description": DEMO_LABEL,
				}
			).insert(ignore_permissions=True)

		company = run.ensure("setup:company", create_company)

	abbr = frappe.get_cached_value("Company", company, "abbr")

	def create_address():
		rng = rng_for(run, "company-address")
		return frappe.get_doc(
			{
				"doctype": "Address",
				**locale.company_address(rng, company, home_state, bool(params.use_wizard_company)),
				"is_your_company_address": 1,
				"is_primary_address": 1,
				"links": [{"link_doctype": "Company", "link_name": company}],
			}
		).insert(ignore_permissions=True)

	if locale.wants_company_address(params):
		run.ensure("setup:company-address", create_address)

	parent_warehouse = frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 1, "parent_warehouse": ["is", "not set"]}
	)
	supplies_store = (pack.get("supplies") or {}).get("warehouse")
	for wh in pack["company"]["warehouses"] + ([supplies_store] if supplies_store else []):
		if frappe.db.exists("Warehouse", f"{wh} - {abbr}"):
			continue  # created with the company (e.g. Stores); the company owns it
		run.ensure(
			f"setup:warehouse:{wh}",
			lambda wh=wh: frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": wh,
					"company": company,
					"parent_warehouse": parent_warehouse,
				}
			).insert(ignore_permissions=True),
		)

	start, end = date_range(getdate(params.end_date), params.months)
	for fy_start in fiscal_year_starts(start, end, locale):
		ensure_fiscal_year(run, fy_start, company, locale)

	ensure_price_lists(run, company)
	locale.setup_taxes(run, company, abbr, pack)  # India: no-ITC templates (--unregistered), SEZ switch
	setup_banking(run, company, abbr, pack)

	set_defaults(run, company)
	return company


def ensure_fiscal_year(run: Run, fy_start: date, company: str, locale=None):
	"""The demo company's fiscal year starting fy_start: the site's own when it has one with
	the same dates, otherwise a new one.

	When the site's years run on another calendar (India April to March; the US, UAE and
	Germany January to December), the new year is limited to the demo company (F-53).
	ERPNext allows such an overlap and gives a company its own years first
	(_get_fiscal_years), so the demo uses its calendar and the site's other companies keep
	theirs.
	"""
	fy_end = (locale or get_locale()).fiscal_year_end(fy_start)
	for fy in frappe.get_all(
		"Fiscal Year",
		filters={"year_start_date": fy_start, "year_end_date": fy_end},
		fields=["name", "disabled"],
	):
		companies = frappe.get_all("Fiscal Year Company", {"parent": fy.name}, pluck="company")
		if companies and company not in companies:
			continue  # another company's year
		if fy.disabled:
			frappe.throw(f"Fiscal Year {fy.name} is disabled; enable it or pick another --end-date")
		return
	overlapping = frappe.get_all(
		"Fiscal Year",
		filters={"year_start_date": ["<=", fy_end], "year_end_date": [">=", fy_start]},
		pluck="name",
	)
	label = f"{fy_start.year}-{fy_end.year}" if fy_end.year != fy_start.year else str(fy_start.year)
	limited = bool(overlapping)
	if limited:
		abbr = frappe.get_cached_value("Company", company, "abbr")
		label = f"{label} ({abbr})"
	run.ensure(
		f"setup:fiscal-year:{fy_start.year}",
		lambda: frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": label,
				"year_start_date": fy_start,
				"year_end_date": fy_end,
				"companies": [{"company": company}] if limited else [],
			}
		).insert(ignore_permissions=True),
	)


def ensure_price_lists(run: Run, company: str):
	"""Price lists in the demo company's currency. The site's defaults (Selling and Buying
	Settings) are used when they are in that currency; on a site set up for another country
	the demo gets "Standard Selling (INR)" and so on, recorded for uninstall (F-53)."""
	currency = frappe.get_cached_value("Company", company, "default_currency")
	chosen = {}
	for role, settings, flag in (("selling", "Selling Settings", "selling"), ("buying", "Buying Settings", "buying")):
		default = frappe.db.get_single_value(settings, f"{role}_price_list") or f"Standard {role.title()}"
		if frappe.db.get_value("Price List", default, "currency") == currency:
			chosen[role] = default
			continue
		name = f"Standard {role.title()} ({currency})"
		if not frappe.db.exists("Price List", name):
			run.ensure(
				f"setup:price-list:{role}",
				lambda name=name, flag=flag: frappe.get_doc(
					{"doctype": "Price List", "price_list_name": name, "currency": currency, flag: 1, "enabled": 1}
				).insert(ignore_permissions=True),
			)
		chosen[role] = name
	run.update_params(price_lists=chosen)


BANK_MODES = ("Wire Transfer", "Cheque", "Bank Draft", "Credit Card")  # ERPNext's own; go to the main account
ACCOUNT_LABELS = {"main": "Current A/c (demo)", "collection": "Collection A/c (demo)"}


def _free_name(taken, base: str) -> str:
	"""base, or base with a letter (B, C, ...) when taken(name) says it is in use."""
	if not taken(base):
		return base
	for letter in "BCDEFGHIJKLMNOPQRSTUVWXYZ":
		if not taken(f"{base} {letter}"):
			return f"{base} {letter}"
	frappe.throw(f"No free name for {base!r}")


def setup_banking(run: Run, company: str, abbr: str, pack: dict):
	"""The demo's own bank accounts (main and collection), their ledgers, and payment modes.

	The accounts are always new, even when the company already banks with the same
	bank (then they are "... B"), so demo payments never touch the user's accounts;
	uninstall removes them. An existing Bank master is only the bank's name and is
	reused, not registered. Account numbers and IFSC codes are made up. UPI and card
	modes carry the receiving bank ("UPI - ICICI"): ERPNext maps a mode of payment to
	one account per company.
	"""
	from erpnext_demo_gen.planner.transactions import planned_mode_names

	locale = get_locale(pack)
	cfg = pack["banking"]
	parent = frappe.db.get_value(
		"Account", {"company": company, "account_type": "Bank", "is_group": 1}, order_by="lft"
	)
	banking = run.params.get("banking") or {"modes_added": []}
	accounts = {}
	for role in ("main", "collection"):
		bank_name, label = cfg[role]["bank"], ACCOUNT_LABELS[role]
		if not frappe.db.exists("Bank", bank_name):
			run.ensure(
				f"setup:bank:{role}",
				lambda b=bank_name: frappe.get_doc({"doctype": "Bank", "bank_name": b}).insert(ignore_permissions=True),
			)

		def create_ledger(bank_name=bank_name, label=label):
			name = _free_name(
				lambda n: frappe.db.exists("Account", {"company": company, "account_name": n}),
				f"{bank_name} {label}",
			)
			return frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": name,
					"company": company,
					"parent_account": parent,
					"account_type": "Bank",
					"account_currency": locale.currency,
				}
			).insert(ignore_permissions=True)

		ledger = run.ensure("setup:account:bank" + ("" if role == "main" else f":{role}"), create_ledger)

		def create_bank_account(role=role, bank_name=bank_name, label=label, ledger=ledger):
			rng = rng_for(run, f"bank-account:{role}")
			name = _free_name(lambda n: frappe.db.exists("Bank Account", f"{n} - {bank_name}"), label)
			return frappe.get_doc(
				{
					"doctype": "Bank Account",
					"account_name": name,
					"bank": bank_name,
					"account": ledger,
					"company": company,
					"is_company_account": 1,
					# a company the user keeps may have its own default bank account
					"is_default": int(role == "main" and not run.params.use_wizard_company),
					**locale.bank_account_fields(rng, cfg[role]),
				}
			).insert(ignore_permissions=True)

		bank_account = run.ensure("setup:bank-account" + ("" if role == "main" else f":{role}"), create_bank_account)
		accounts[role] = {"ledger": ledger, "bank_account": bank_account}

	main, collection = accounts["main"]["ledger"], accounts["collection"]["ledger"]
	cash = frappe.get_cached_value("Company", company, "default_cash_account")
	# which ledger each mode posts to in this company
	targets = {"Cash": cash, **dict.fromkeys(BANK_MODES, main)}
	for mode in sorted(planned_mode_names(cfg, locale.counter_modes)):
		targets.setdefault(mode, collection if mode.endswith(f" - {cfg['collection']['short']}") else main)
		if not frappe.db.exists("Mode of Payment", mode):
			run.ensure(
				f"setup:mode-of-payment:{mode}",
				lambda m=mode: frappe.get_doc(
					{"doctype": "Mode of Payment", "mode_of_payment": m, "type": "Bank", "enabled": 1}
				).insert(ignore_permissions=True),
			)

	# Record every change, so uninstall can undo it in a company that stays (wizard mode).
	banking.update(accounts=accounts, bank_ledger=main, bank_account=accounts["main"]["bank_account"])
	previous = frappe.db.get_value("Company", company, "default_bank_account")
	if not previous:
		frappe.db.set_value("Company", company, "default_bank_account", main)
		banking.update(set_default_bank=True, previous_default_bank=None)
	for mode, account in targets.items():
		if not frappe.db.exists("Mode of Payment", mode):
			continue
		doc = frappe.get_doc("Mode of Payment", mode)
		if not any(row.company == company for row in doc.accounts):
			# Company.on_trash deletes these rows, so they need no registry entry
			doc.append("accounts", {"company": company, "default_account": account})
			doc.flags.ignore_permissions = True
			doc.save()
			banking["modes_added"] = sorted({*banking["modes_added"], mode})
	run.update_params(banking=banking)
	frappe.db.commit()


def set_defaults(run: Run, company: str):
	if "previous_default_company" not in run.params:
		run.update_params(
			previous_default_company=frappe.db.get_single_value("Global Defaults", "default_company")
		)
	set_default_company(company)
	frappe.db.commit()


def set_default_company(company: str | None):
	"""Set the default company without saving Global Defaults.

	Saving it runs on_update, which deletes and recreates rounding and in-words
	Property Setters and queues a cleanup job for each; we only need the default.
	"""
	frappe.db.set_single_value("Global Defaults", "default_company", company)
	frappe.db.set_default("company", company or "")
	frappe.clear_cache()
