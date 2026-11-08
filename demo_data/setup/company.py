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

	setup_banking(run, company, abbr)

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


BANK_ACCOUNT_NAME = "Bank Current Account"
BANK_MODES = ("Wire Transfer", "Cheque", "Bank Draft", "Credit Card")


def setup_banking(run: Run, company: str, abbr: str):
	"""A bank ledger account as the company's default bank, and mode-of-payment accounts.

	Payment Entry takes the company's default bank account; without one, receipts
	and payments would all post to Cash.
	"""
	parent = frappe.db.get_value(
		"Account", {"company": company, "account_type": "Bank", "is_group": 1}, order_by="lft"
	)
	bank = run.ensure(
		"setup:account:bank",
		lambda: frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": BANK_ACCOUNT_NAME,
				"company": company,
				"parent_account": parent,
				"account_type": "Bank",
				"account_currency": "INR",
			}
		).insert(ignore_permissions=True),
	)
	# Record every change, so uninstall can undo it in a company that stays (wizard mode).
	banking = run.params.get("banking") or {"modes_added": []}
	previous = frappe.db.get_value("Company", company, "default_bank_account")
	if not previous:
		frappe.db.set_value("Company", company, "default_bank_account", bank)
		banking.update(set_default_bank=True, previous_default_bank=None)
	cash = frappe.get_cached_value("Company", company, "default_cash_account")
	for mode in frappe.get_all("Mode of Payment", filters={"enabled": 1}, fields=["name", "type"]):
		account = (
			cash if mode.type == "Cash" else bank if mode.name in BANK_MODES or mode.type == "Bank" else None
		)
		if not account:
			continue
		doc = frappe.get_doc("Mode of Payment", mode.name)
		if not any(row.company == company for row in doc.accounts):
			# Company.on_trash deletes these rows, so they need no registry entry
			doc.append("accounts", {"company": company, "default_account": account})
			doc.flags.ignore_permissions = True
			doc.save()
			banking["modes_added"] = sorted({*banking["modes_added"], mode.name})
	run.update_params(banking=banking)
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
