"""Demo company and India set-up (milestone 1).

With --no-gst no address is created, so the company stays unregistered for GST. In
wizard mode the company is the user's; only --fictitious-gstin adds an address to it.

Creates, through the registry: the demo Company (ERPNext installs India
fixtures and india_compliance adds GST accounts and tax templates, F-5), its
GSTIN-bearing Address, the pack's warehouses and every Fiscal Year the date
range touches. Then makes the demo company the default and registers it as
ERPNext's demo company (DEC-19), remembering the previous default for uninstall.
"""

import random
from datetime import date

import frappe
from frappe.utils import add_days, add_months, getdate

from demo_data import naming
from demo_data.india import geo
from demo_data.india.gstin import make_gstin, make_pan
from demo_data.registry import Run
from demo_data.setup.tax_templates import ensure_no_itc_templates, purge_orphans

DEMO_LABEL = "Fictional company created by the demo_data app. All names, GSTINs and figures are made up."


def rng_for(run: Run, purpose: str) -> random.Random:
	"""A deterministic random stream per purpose, so adding one stream never shifts another."""
	return random.Random(f"{run.params.seed}:{purpose}")


def date_range(end_date: date, months: int) -> tuple[date, date]:
	return add_days(add_months(end_date, -months), 1), end_date


def fiscal_year_starts(start: date, end: date) -> list[date]:
	"""April-to-March fiscal years that the range touches."""
	first = start.year if start.month >= 4 else start.year - 1
	last = end.year if end.month >= 4 else end.year - 1
	return [date(y, 4, 1) for y in range(first, last + 1)]


def choose_company_name(run: Run, pack: dict) -> str:
	if run.params.get("company"):
		return run.params.company
	rng = rng_for(run, "company-name")
	for _ in range(50):
		name = naming.company_name(rng, pack["company"]["industry_nouns"], "Pvt Ltd")
		if not frappe.db.exists("Company", name):
			return name
	frappe.throw("Could not find an unused company name; pass --demo-company-name")


def setup_company(run: Run, pack: dict) -> str:
	params = run.params
	home_state = params.home_state

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
					"country": "India",
					"default_currency": "INR",
					"chart_of_accounts": "Standard",
					"default_gst_rate": "18.0",  # Select field of strings (F-24)
					"company_description": DEMO_LABEL,
					**({"gst_category": "Unregistered"} if params.get("gst") == "unregistered" else {}),
				}
			).insert(ignore_permissions=True)

		company = run.ensure("setup:company", create_company)

	abbr = frappe.get_cached_value("Company", company, "abbr")

	def create_address():
		rng = rng_for(run, "company-address")
		gstin = make_gstin(geo.state_code(home_state), make_pan(rng, "company", company))
		# in the user's own company, say plainly that the GSTIN is made up
		title = f"{company} (demo, fictitious GSTIN)" if params.use_wizard_company else company
		return frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": title,
				"address_type": "Billing",
				**geo.make_address(rng, home_state),
				"gstin": gstin,
				"gst_category": "Registered Regular",
				"is_your_company_address": 1,
				"is_primary_address": 1,
				"links": [{"link_doctype": "Company", "link_name": company}],
			}
		).insert(ignore_permissions=True)

	if params.get("gst") != "unregistered" and (not params.use_wizard_company or params.get("fictitious_gstin")):
		run.ensure("setup:company-address", create_address)

	parent_warehouse = frappe.db.get_value(
		"Warehouse", {"company": company, "is_group": 1, "parent_warehouse": ["is", "not set"]}
	)
	for wh in pack["company"]["warehouses"]:
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
	for fy_start in fiscal_year_starts(start, end):
		ensure_fiscal_year(run, fy_start, company)

	if params.get("gst") == "unregistered":
		ensure_no_itc_templates(run, company, abbr)

	setup_banking(run, company, abbr, pack)
	enable_sez(run, pack)

	set_defaults(run, company)
	return company


def ensure_fiscal_year(run: Run, fy_start: date, company: str):
	existing = frappe.db.get_value(
		"Fiscal Year", {"year_start_date": fy_start}, ["name", "disabled"], as_dict=True
	)
	if existing:
		companies = frappe.get_all("Fiscal Year Company", {"parent": existing.name}, pluck="company")
		if companies and company not in companies:
			frappe.throw(
				f"Fiscal Year {existing.name} is limited to {', '.join(companies)}; "
				"a demo company cannot share it yet. Remove the company restriction or pick another --end-date."
			)
		if existing.disabled:
			frappe.throw(f"Fiscal Year {existing.name} is disabled")
		return
	fy_end = date(fy_start.year + 1, 3, 31)
	run.ensure(
		f"setup:fiscal-year:{fy_start.year}",
		lambda: frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": f"{fy_start.year}-{fy_end.year}",
				"year_start_date": fy_start,
				"year_end_date": fy_end,
			}
		).insert(ignore_permissions=True),
	)


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
	from demo_data.planner.transactions import planned_mode_names

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
					"account_currency": "INR",
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
					"bank_account_no": "".join(str(rng.randint(0, 9)) for _ in range(14)),
					"branch_code": f"{cfg[role]['ifsc_prefix']}0{rng.randint(0, 999999):06d}",
				}
			).insert(ignore_permissions=True)

		bank_account = run.ensure("setup:bank-account" + ("" if role == "main" else f":{role}"), create_bank_account)
		accounts[role] = {"ledger": ledger, "bank_account": bank_account}

	main, collection = accounts["main"]["ledger"], accounts["collection"]["ledger"]
	cash = frappe.get_cached_value("Company", company, "default_cash_account")
	# which ledger each mode posts to in this company
	targets = {"Cash": cash, **dict.fromkeys(BANK_MODES, main)}
	for mode in sorted(planned_mode_names(cfg)):
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


def enable_sez(run: Run, pack: dict):
	"""SEZ customers need GST Settings' "Enable SEZ / Overseas Transactions", as a real
	business with SEZ customers would have; india_compliance refuses their orders
	otherwise. A site-wide setting, so the previous value is recorded and uninstall
	restores it. Not needed without GST (--no-gst plans no SEZ customers)."""
	if not pack["behavior"]["gst_categories"].get("sez") or run.params.get("gst") == "unregistered":
		return
	if "gst_settings" in run.params:
		return  # recorded on a previous attempt
	previous = frappe.db.get_single_value("GST Settings", "enable_overseas_transactions")
	run.update_params(gst_settings={"enable_overseas_transactions": previous})
	if not previous:
		frappe.db.set_single_value("GST Settings", "enable_overseas_transactions", 1)
	frappe.db.commit()


def set_defaults(run: Run, company: str):
	if "previous_default_company" not in run.params:
		run.update_params(
			previous_default_company=frappe.db.get_single_value("Global Defaults", "default_company")
		)
	set_default_company(company, demo_company=None if run.params.use_wizard_company else company)
	frappe.db.commit()


def set_default_company(company: str | None, demo_company: str | None = None):
	"""Set the default (and demo) company without saving Global Defaults.

	Saving it runs on_update, which deletes and recreates rounding and in-words
	Property Setters and queues a cleanup job for each; we only need the default.
	"""
	values = {"default_company": company}
	if demo_company is not None or frappe.db.get_single_value("Global Defaults", "demo_company") == company:
		values["demo_company"] = demo_company
	frappe.db.set_single_value("Global Defaults", values)
	frappe.db.set_default("company", company or "")
	frappe.clear_cache()
