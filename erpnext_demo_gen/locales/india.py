"""India: GST registration categories, GSTIN and PAN, states and pincodes."""

import importlib.util
import json
import os
import random
from functools import cache

from erpnext_demo_gen import naming
from erpnext_demo_gen.india import geo
from erpnext_demo_gen.india.gstin import make_gstin, make_pan
from erpnext_demo_gen.locales import Locale
from erpnext_demo_gen.planner import weighted

GST_CATEGORIES = {"registered": "Registered Regular", "sez": "SEZ"}  # else "Unregistered"
# rates for which india_compliance creates an Item Tax Template ("GST <rate>% - <abbr>")
GST_RATES = (5, 12, 18, 28)


@cache
def hsn_codes() -> frozenset[str]:
	"""HSN codes shipped with india_compliance (the GST HSN Code master)."""
	spec = importlib.util.find_spec("india_compliance")
	if not spec or not spec.submodule_search_locations:
		return frozenset()
	path = os.path.join(spec.submodule_search_locations[0], "gst_india", "data", "hsn_codes.json")
	with open(path) as f:
		return frozenset(str(row["hsn_code"]) for row in json.load(f))


@cache
def indian_states() -> frozenset[str]:
	try:
		from india_compliance.gst_india.constants import STATE_NUMBERS
	except ImportError:
		return frozenset()
	return frozenset(STATE_NUMBERS) - {"Other Countries", "Other Territory"}


class IndiaLocale(Locale):
	code = "IN"
	country = "India"
	aliases = ("Bharat",)

	# ---------------------------------------------------------- planning (pure)
	season_start_month = 4  # seasonality index 0 = April, the fiscal year start

	def regions(self) -> list[str]:
		return sorted(geo.PARTY_STATES)

	def home_regions(self) -> list[str]:
		return sorted(geo.CITIES)

	def person(self, rng: random.Random, region: str) -> tuple[str, str]:
		return naming.person(rng, region)

	def business_name(self, rng: random.Random, nouns: list[str]) -> str:
		return naming.company_name(rng, nouns)

	def phone(self, rng: random.Random) -> str:
		return naming.mobile(rng)

	def company_name(self, rng: random.Random, nouns: list[str]) -> str:
		return naming.company_name(rng, nouns, self.company_suffix)

	def address(self, rng: random.Random, region: str) -> dict:
		return geo.make_address(rng, region)

	def business_tax(self, rng: random.Random, name: str, region: str, registered: bool, category: str) -> dict:
		"""A registered business has a GSTIN (its PAN inside it); an unregistered one only a PAN."""
		pan = make_pan(rng, "company", name)
		return {
			"gst_category": category if registered else "Unregistered",
			"gstin": make_gstin(geo.state_code(region), pan) if registered else None,
			"pan": None if registered else pan,
		}

	def individual_tax(self) -> dict:
		return {"gst_category": "Unregistered"}

	def customer_category(self, rng: random.Random, behavior: dict, sales_tax: bool) -> tuple[bool, str]:
		"""Drawn from behavior.gst_categories. An unregistered seller cannot supply SEZ
		units (an inter-state supply, which needs GST registration at any turnover)."""
		category = weighted(rng, behavior["gst_categories"])
		if category == "sez" and not sales_tax:
			category = "registered"
		return category != "unregistered", GST_CATEGORIES.get(category, "Unregistered")

	def customer_home_share(self, behavior: dict, sales_tax: bool) -> float:
		"""An unregistered seller cannot supply goods to other states either."""
		return behavior["geography"]["home_state_share"] if sales_tax else 1.0

	def item_tax(self, family: dict, pack: dict) -> dict:
		"""HSN code (india_compliance's gst_hsn_code) and GST rate of the family."""
		return {"hsn": str(family["hsn"]), "gst_rate": family["gst_rate"]}

	def item_tax_rate(self, item_params: dict) -> float:
		return item_params["gst_rate"]

	prices_include_tax = True  # retail shelf prices include GST

	# ---------------------------------------------------------- payments
	payment_modes = ("Cash", "UPI", "Wire Transfer", "Cheque", "Card")
	counter_modes = ("UPI", "Card")  # the counter's UPI QR and card terminal pay into the collection account

	def mode_limit(self, mode: str, banking: dict) -> float | None:
		return banking["upi_limit"] if mode == "UPI" else None

	def over_limit_mode(self, mode: str) -> str:
		return "Wire Transfer"  # NEFT or RTGS

	def payment_reference(self, rng: random.Random, mode: str, amount: float, when, bank: dict, banking: dict) -> str:
		if mode == "Cheque":
			return f"{rng.randint(100000, 999999)}"
		if mode == "Wire Transfer":  # NEFT/RTGS UTR: bank code, N or R, date, serial
			kind = "R" if amount >= banking["rtgs_from"] else "N"
			return f"{bank['ifsc_prefix']}{kind}{when:%y%m%d}{rng.randint(10**7, 10**8 - 1)}"
		return f"{when:%y}{rng.randint(10**9, 10**10 - 1)}"  # UPI and card: 12-digit RRN

	def sweep_reference(self, rng: random.Random, source: str, when, banking: dict) -> str:
		if source == "collection":  # NEFT between the company's own accounts
			return f"{banking['collection']['ifsc_prefix']}N{when:%y%m%d}{rng.randint(10**7, 10**8 - 1)}"
		return f"DEP{when:%y%m%d}{rng.randint(100, 999)}"  # cash deposit slip

	# ---------------------------------------------------------- setup
	currency = "INR"
	company_suffix = "Pvt Ltd"
	timezone = "Asia/Kolkata"

	def company_fields(self, params) -> dict:
		return {
			"country": "India",
			"default_currency": "INR",
			"chart_of_accounts": "Standard",
			"default_gst_rate": "18.0",  # Select field of strings (F-24)
			**({"gst_category": "Unregistered"} if params.get("gst") == "unregistered" else {}),
		}

	def wants_company_address(self, params) -> bool:
		"""The GSTIN lives on the company address: none with --no-gst, and in wizard mode
		only with --fictitious-gstin (the user's own company otherwise stays as it is)."""
		return params.get("gst") != "unregistered" and (not params.use_wizard_company or params.get("fictitious_gstin"))

	def company_address(self, rng: random.Random, company: str, region: str, wizard: bool) -> dict:
		gstin = make_gstin(geo.state_code(region), make_pan(rng, "company", company))
		# in the user's own company, say plainly that the GSTIN is made up
		title = f"{company} (demo, fictitious GSTIN)" if wizard else company
		return {
			"address_title": title,
			"address_type": "Billing",
			**geo.make_address(rng, region),
			"gstin": gstin,
			"gst_category": "Registered Regular",
		}

	def fiscal_year_starts(self, start, end) -> list:
		"""April-to-March fiscal years that the range touches."""
		from datetime import date

		first = start.year if start.month >= 4 else start.year - 1
		last = end.year if end.month >= 4 else end.year - 1
		return [date(y, 4, 1) for y in range(first, last + 1)]

	def fiscal_year_end(self, fy_start):
		from datetime import date

		return date(fy_start.year + 1, 3, 31)

	def setup_taxes(self, run, company: str, abbr: str, pack: dict):
		"""No-ITC purchase templates for an unregistered company (--no-gst), and GST
		Settings' SEZ switch when the pack sells to SEZ units."""
		from erpnext_demo_gen.setup.tax_templates import ensure_no_itc_templates

		if run.params.get("gst") == "unregistered":
			ensure_no_itc_templates(run, company, abbr)
		self._enable_sez(run, pack)

	def _enable_sez(self, run, pack: dict):
		"""SEZ customers need GST Settings' "Enable SEZ / Overseas Transactions", as a real
		business with SEZ customers would have; india_compliance refuses their orders
		otherwise. A site-wide setting, so the previous value is recorded and uninstall
		restores it. Not needed without GST (--no-gst plans no SEZ customers)."""
		import frappe

		if not pack["behavior"]["gst_categories"].get("sez") or run.params.get("gst") == "unregistered":
			return
		if "gst_settings" in run.params:
			return  # recorded on a previous attempt
		previous = frappe.db.get_single_value("GST Settings", "enable_overseas_transactions")
		run.update_params(gst_settings={"enable_overseas_transactions": previous})
		if not previous:
			frappe.db.set_single_value("GST Settings", "enable_overseas_transactions", 1)
		frappe.db.commit()

	def bank_account_fields(self, rng: random.Random, bank: dict) -> dict:
		"""14-digit account number and an IFSC (bank prefix, 0, six digits)."""
		return {
			"bank_account_no": "".join(str(rng.randint(0, 9)) for _ in range(14)),
			"branch_code": f"{bank['ifsc_prefix']}0{rng.randint(0, 999999):06d}",
		}

	# ---------------------------------------------------------- writing documents
	def writer_context(self, run, company: str) -> dict:
		"""india_compliance's Item Tax Templates by GST rate ("GST 18% - ABC"), the
		India territory, and the home state's GST code (for --no-gst purchases)."""
		import frappe
		from frappe.utils.nestedset import get_root_of

		templates = {}
		for row in frappe.get_all(
			"Item Tax Template",
			filters={"company": company, "disabled": 0, "gst_rate": [">", 0]},
			fields=["name", "gst_rate"],
			order_by="name",
		):
			templates.setdefault(float(row.gst_rate), row.name)
		return {
			"territory": "India" if frappe.db.exists("Territory", "India") else get_root_of("Territory"),
			"tax_templates": templates,
			"locale_data": {"home_state_code": geo.state_code(run.params.home_state)},
		}

	def party_fields(self, p, w) -> dict:
		"""Fields india_compliance's party hooks use: GSTIN and category, and _address_line1
		etc. for the primary address its after_insert hook creates (F-25)."""
		address = p.get("address") or {}
		fields = {"gst_category": p.gst_category, "country": "India"}
		if p.get("gstin"):
			fields["gstin"] = p.gstin
		elif p.get("pan"):
			fields["pan"] = p.pan
		if address:
			fields.update(
				{
					"_address_line1": address["address_line1"],
					"city": address["city"],
					"state": address["state"],
					"pincode": address["pincode"],
					"is_primary_address": 1,
					"is_shipping_address": 1,
				}
			)
		return fields

	def item_fields(self, p, w) -> dict:
		return {"gst_hsn_code": p.hsn, "taxes": [{"item_tax_template": w.item_tax_template(p.gst_rate)}]}

	def purchase_taxes(self, doc, w):
		"""Unregistered company (--no-gst): nothing picks a template (F-38), so select the
		no-ITC one by the supplier's state, as the user would; an unregistered supplier
		charges none. A registered company keeps what ERPNext picks."""
		if w.tax_registered:
			return
		import frappe

		from erpnext_demo_gen.setup.tax_templates import no_itc_template

		gstin = frappe.db.get_value("Supplier", doc.supplier, "gstin")
		if gstin:
			place = "In" if gstin[:2] == w.locale_data["home_state_code"] else "Out"
			doc.taxes_and_charges = no_itc_template(place, w.abbr)

	# ---------------------------------------------------------- install parameters
	required_apps = ("erpnext", "india_compliance")
	snapshot_install_args = ("--fictitious-gstin",)  # the build site's wizard company has no GSTIN
	unregistered_warning = (
		"generating without GST: the company is unregistered, so sales carry no GST and the GST "
		"paid on purchases becomes part of their cost (no input tax credit). This demo's turnover "
		"is above the GST registration threshold (Rs 40 lakh a year for goods, Rs 20 lakh in "
		"special-category states), so a real business like it would have to register. All customers "
		"are in the home state: an unregistered business cannot sell goods to other states"
	)

	def preflight_problems(self) -> list[str]:
		from india_compliance.gst_india.utils import is_api_enabled

		if is_api_enabled():
			return [
				"india_compliance's GST API is enabled; generated invoices could reach the GST portal "
				"(e-invoice, e-waybill, GSTIN lookups)"
			]
		return []

	def resolve_region(self, text: str) -> str | None:
		return geo.resolve_state(text)

	def region_choices(self) -> str:
		return ", ".join(f"{geo.STATE_ABBREVIATIONS[s]} ({s})" for s in sorted(geo.CITIES))

	def validate_pack(self, pack: dict, check):
		"""Home state, HSN codes and GST rates (india_compliance's), Indian bank details."""
		states = indian_states()
		state = (pack.get("company") or {}).get("home_state")
		check(isinstance(state, str) and state and (not states or state in states), "company.home_state", f"unknown state {state!r}")
		known_hsn = hsn_codes()
		for i, f in enumerate((pack.get("catalog") or {}).get("families") or []):
			p = f"catalog.families[{i}]"
			hsn = str(f.get("hsn") or "")
			check(len(hsn) in (6, 8) and hsn.isdigit(), f"{p}.hsn", "must be 6 or 8 digits (GST Settings default minimum is 6)")
			if known_hsn:
				check(hsn in known_hsn, f"{p}.hsn", f"{hsn!r} is not in india_compliance's HSN list")
			check(f.get("gst_rate") in GST_RATES, f"{p}.gst_rate", f"must be one of {GST_RATES}")
		values = (pack.get("behavior") or {}).get("gst_categories") or {}
		check(values and abs(sum(values.values()) - 1) < 1e-6, "behavior.gst_categories", "shares must add up to 1")
		banking = pack.get("banking") or {}
		for role in ("main", "collection"):
			prefix = (banking.get(role) or {}).get("ifsc_prefix") or ""
			check(len(prefix) == 4 and prefix.isalpha() and prefix.isupper(), f"banking.{role}.ifsc_prefix", "must be 4 capital letters")
		for key in ("upi_limit", "rtgs_from"):
			value = banking.get(key)
			check(isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 1, f"banking.{key}", "must be a positive number")

	def company_gst_state(self, company: str) -> str | None:
		"""The GST state of the company's own GSTIN address, or None when it has none. Without
		one, india_compliance treats the company as unregistered and charges no GST (F-37)."""
		import frappe

		addresses = frappe.get_all(
			"Address",
			filters=[
				["Dynamic Link", "link_doctype", "=", "Company"],
				["Dynamic Link", "link_name", "=", company],
				["is_your_company_address", "=", 1],
				["gstin", "is", "set"],
				["disabled", "=", 0],
			],
			fields=["gst_state"],
			order_by="is_primary_address desc, creation asc",
			limit=1,
		)
		return addresses[0].gst_state if addresses else None

	def check_wizard_company(self, company: str, params: dict, home_region: str | None, unregistered: bool, fictitious_id: bool):
		"""Wizard mode needs to know the company's GST state: from its GSTIN address, or a
		made-up GSTIN (--fictitious-gstin), or none at all (--no-gst)."""
		from erpnext_demo_gen.service import DemoDataError

		state = self.company_gst_state(company)
		if state and (unregistered or fictitious_id):
			raise DemoDataError(
				f"{company!r} is already GST-registered (state {state}); leave out --no-gst and --fictitious-gstin"
			)
		if state:
			if home_region and home_region != state:
				raise DemoDataError(
					f"--home-state {home_region!r} differs from the GST state of {company!r} ({state}); "
					"leave --home-state out in wizard mode"
				)
			params["home_state"] = state
		elif fictitious_id:
			params["fictitious_gstin"] = True  # setup adds a labelled address; uninstall removes it
		elif not unregistered:
			raise DemoDataError(
				f"{company!r} has no GSTIN (no company address with one), so it is unregistered for GST "
				"and india_compliance charges no GST (F-37). Either add your company address with its "
				"GSTIN, or pass --fictitious-gstin to have the demo add an address with a made-up GSTIN "
				"(removed on uninstall), or pass --no-gst --force to generate the demo without GST."
			)

	# ---------------------------------------------------------- verify
	def tax_checks(self, ctx) -> list:
		return [self._gst_rows(ctx)]

	def _gst_rows(self, ctx):
		"""GST rows match the company's registration.

		Registered (F-16): every submitted sale and every purchase from a GST-registered
		supplier carries GST rows, except zero-rated SEZ and export supplies made without
		GST (under a bond). Unregistered (--no-gst): sales carry none, and those
		purchases carry GST as part of cost ("Valuation and Total"), since no credit can
		be claimed.
		"""
		import frappe

		from erpnext_demo_gen.verify import Check

		registered = ctx.run.params.get("gst", "registered") == "registered"
		wrong = []
		sales_rows = "exists" if registered else "not exists"
		# SEZ and export supplies are zero-rated: without "export with GST" (supply under a
		# bond, LUT) they rightly carry no GST rows, so the registered check skips them
		zero_rated = (
			"and not (d.gst_category in ('SEZ', 'Overseas') and ifnull(d.is_export_with_gst, 0) = 0)" if registered else ""
		)
		for doctype in ("Quotation", "Sales Order", "Sales Invoice"):
			wrong += frappe.db.sql_list(
				f"""select d.name from `tab{doctype}` d where d.company=%s and d.docstatus=1 {zero_rated}
				and not {sales_rows} (select 1 from `tabSales Taxes and Charges` t where t.parent=d.name)""",
				(ctx.company,),
			)
		cost_only = "" if registered else "and t.category = 'Valuation and Total'"
		for doctype in ("Purchase Order", "Purchase Invoice"):
			wrong += frappe.db.sql_list(
				f"""select d.name from `tab{doctype}` d join tabSupplier s on s.name=d.supplier
				where d.company=%s and d.docstatus=1 and s.gst_category != 'Unregistered'
				and not exists (select 1 from `tabPurchase Taxes and Charges` t
					where t.parent=d.name {cost_only})""",
				(ctx.company,),
			)
		if wrong and ctx.run.params.get("use_wizard_company"):
			# the wizard company also holds the user's own documents; judge only the run's
			ours = set(
				frappe.get_all(
					"Demo Data Record", filters={"run": ctx.run.name, "ref_name": ["in", wrong]}, pluck="ref_name"
				)
			)
			wrong = [name for name in wrong if name in ours]
		if registered:
			return Check("taxable documents have GST rows", not wrong, ", ".join(wrong[:5]) or "all present")
		return Check(
			"no GST on sales, purchase GST in cost (unregistered)",
			not wrong,
			", ".join(wrong[:5]) or "all as expected",
		)
