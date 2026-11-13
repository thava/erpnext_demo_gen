"""United Arab Emirates: 5% VAT with input credit, emirates, TRNs, AED.

What a VAT-registered UAE trading business looks like in ERPNext's own UAE set-up
(erpnext/regional/united_arab_emirates; the UAE VAT 201 report):

    sales       5% VAT ("UAE VAT 5%"); shelf prices include VAT (UAE consumer rules)
                each invoice carries its VAT Emirate (box 1a-1g of VAT 201), which
                ERPNext fetches from the company address's Emirate field
    purchases   5% VAT from VAT-registered suppliers, recoverable: each bill records it
                as "Recoverable Standard Rated Expenses" (box 9)
    settings    UAE VAT Settings lists the company's VAT account (reverse charge and
                the VAT 201 report use it)

Unregistered (--unregistered; registration is mandatory above AED 375,000 of taxable
supplies in 12 months): sales carry no VAT and the company has no TRN; VAT paid on
purchases cannot be recovered, so it goes to a "VAT Not Recoverable" expense account
through "Valuation and Total" rows (in the cost of stock items, DEC-37); VAT Emirate and
the VAT 201 report do not apply.

Out of scope for the demo: imports and reverse charge, zero-rated exports, tourist
refunds, excise, designated zones. General information, not tax advice.
"""

import random

from erpnext_demo_gen.locales import Locale, squash
from erpnext_demo_gen.planner import weighted

# emirate -> cities (UAE addresses have no postcode; a P.O. Box is usual)
CITIES = {
	"Dubai": ["Dubai", "Jebel Ali", "Al Quoz", "Deira"],
	"Abu Dhabi": ["Abu Dhabi", "Al Ain", "Mussafah"],
	"Sharjah": ["Sharjah", "Khor Fakkan"],
	"Ajman": ["Ajman"],
	"Ras Al Khaimah": ["Ras Al Khaimah"],
	"Fujairah": ["Fujairah"],
	"Umm Al Quwain": ["Umm Al Quwain"],
}
EMIRATE_CODES = {"DU": "Dubai", "AZ": "Abu Dhabi", "SH": "Sharjah", "AJ": "Ajman", "RK": "Ras Al Khaimah", "FU": "Fujairah", "UQ": "Umm Al Quwain"}
STREETS = [
	"Sheikh Zayed Road", "Al Wasl Road", "Al Khail Road", "Jumeirah Beach Road", "Al Maktoum Street",
	"Khalid Bin Al Waleed Road", "Corniche Road", "Al Ittihad Road", "King Faisal Street", "Hamdan Street",
	"Airport Road", "Al Nahda Street", "Industrial Area 4", "Al Rigga Road",
]
FIRST_NAMES = [
	"Ahmed", "Mohammed", "Fatima", "Aisha", "Khalid", "Mariam", "Omar", "Noura", "Saeed", "Hessa",
	"Rashid", "Layla", "Yousef", "Shamma", "Hamdan", "Rahul", "Priya", "Anil", "Imran", "Sana",
	"Maria", "Jose", "Grace", "David", "Sarah", "Ali", "Hassan", "Rania", "Karim", "Nadia",
]
LAST_NAMES = [
	"Al Mansoori", "Al Hashimi", "Al Mazrouei", "Al Nuaimi", "Al Suwaidi", "Al Ketbi", "Al Shamsi",
	"Al Falasi", "Al Marzooqi", "Haddad", "Khoury", "Nair", "Menon", "Qureshi", "Siddiqui", "Santos",
	"Reyes", "Fernandes", "Smith", "Khan", "Rahman", "Saleh", "Aziz", "Mathew",
]
BRAND_WORDS = [
	"Al Noor", "Desert Rose", "Gulf Pearl", "Palm", "Falcon", "Oasis", "Al Waha", "Dune", "Marina",
	"Al Bustan", "Golden Sands", "Crescent", "Al Reef", "Majlis", "Creek", "Sidra", "Ghaf", "Al Fanar",
]
LEGAL_SUFFIXES = ["LLC", "Trading LLC", "FZE", "FZCO"]  # FZE/FZCO: free zone companies


def iban(rng: random.Random, bank_code: str) -> str:
	"""A UAE IBAN with valid check digits (made up): AE, 2 check digits, 3-digit bank code, 16 digits."""
	bban = bank_code + "".join(str(rng.randint(0, 9)) for _ in range(16))
	digits = "".join(str(int(ch, 36)) for ch in bban + "AE00")
	return f"AE{98 - int(digits) % 97:02d}{bban}"


class AELocale(Locale):
	code = "AE"
	country = "United Arab Emirates"
	aliases = ("UAE", "Emirates")

	# ---------------------------------------------------------- planning (pure)
	season_start_month = 1  # seasonality index 0 = January, the fiscal year start

	def regions(self) -> list[str]:
		return sorted(CITIES)

	def person(self, rng: random.Random, region: str) -> tuple[str, str]:
		return rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)

	def business_name(self, rng: random.Random, nouns: list[str]) -> str:
		return f"{rng.choice(BRAND_WORDS)} {rng.choice(nouns)} {rng.choice(LEGAL_SUFFIXES)}"

	def company_name(self, rng: random.Random, nouns: list[str]) -> str:
		return f"{rng.choice(BRAND_WORDS)} {rng.choice(nouns)} {self.company_suffix}"

	def phone(self, rng: random.Random) -> str:
		return f"+971-5{rng.choice('02458')}-{rng.randint(0, 9999999):07d}"

	def address(self, rng: random.Random, region: str) -> dict:
		return {
			"address_line1": f"Office {rng.randint(101, 1999)}, {rng.choice(STREETS)}",
			"address_line2": f"P.O. Box {rng.randint(1000, 99999)}",
			"city": rng.choice(CITIES[region]),
			"state": region,
			"pincode": "",
			"country": "United Arab Emirates",
		}

	def business_tax(self, rng: random.Random, name: str, region: str, registered: bool, category: str) -> dict:
		"""A VAT-registered business has a 15-digit TRN (starting 100)."""
		trn = f"100{rng.randint(0, 10**12 - 1):012d}" if registered else None
		return {"tax_id": trn, "vat_registered": registered}

	def individual_tax(self) -> dict:
		return {}

	def customer_category(self, rng: random.Random, behavior: dict, sales_tax: bool) -> tuple[bool, str]:
		category = weighted(rng, behavior["vat_registration"])
		return category == "registered", category

	def customer_home_share(self, behavior: dict, sales_tax: bool) -> float:
		return behavior["geography"]["home_state_share"]

	def item_tax(self, family: dict, pack: dict) -> dict:
		return {"vat_rate": float(pack["vat"]["rate"])}

	def item_tax_rate(self, item_params: dict) -> float:
		return item_params["vat_rate"]

	prices_include_tax = True  # UAE consumer prices are shown including VAT

	# ---------------------------------------------------------- payments
	payment_modes = ("Cash", "Cheque", "Wire Transfer", "Card")
	counter_modes = ("Card",)  # the card terminal settles into the collection account

	def payment_reference(self, rng: random.Random, mode: str, amount: float, when, bank: dict, banking: dict) -> str:
		if mode == "Cheque":
			return f"{rng.randint(100000, 999999)}"
		if mode == "Wire Transfer":  # bank transfer (UAEFTS) reference
			return f"FT{when:%y%m%d}{rng.randint(10**7, 10**8 - 1)}"
		return f"{rng.randint(100000, 999999)}"  # card approval code

	def sweep_reference(self, rng: random.Random, source: str, when, banking: dict) -> str:
		if source == "collection":
			return f"IT{when:%y%m%d}{rng.randint(1000, 9999)}"
		return f"CDM{when:%y%m%d}{rng.randint(100, 999)}"  # cash deposit machine slip

	# ---------------------------------------------------------- setup
	currency = "AED"
	company_suffix = "LLC"
	timezone = "Asia/Dubai"

	def company_fields(self, params) -> dict:
		rng = random.Random(f"{params.seed}:company-trn")
		fields = {"country": "United Arab Emirates", "default_currency": "AED", "chart_of_accounts": "Standard"}
		if params.get("registration") != "unregistered":
			fields["tax_id"] = f"100{rng.randint(0, 10**12 - 1):012d}"  # the company's TRN
		return fields

	def wants_company_address(self, params) -> bool:
		return True

	def company_address(self, rng: random.Random, company: str, region: str, wizard: bool) -> dict:
		"""The Emirate field (ERPNext's UAE custom field) is what invoices fetch as their VAT Emirate."""
		return {"address_title": company, "address_type": "Billing", **self.address(rng, region), "emirate": region}

	def fiscal_year_starts(self, start, end) -> list:
		from datetime import date

		return [date(y, 1, 1) for y in range(start.year, end.year + 1)]

	def fiscal_year_end(self, fy_start):
		from datetime import date

		return date(fy_start.year, 12, 31)

	def bank_account_fields(self, rng: random.Random, bank: dict) -> dict:
		number = iban(rng, bank["bank_code"])
		return {"iban": number, "bank_account_no": number[-16:], "branch_code": bank["swift"]}

	def setup_taxes(self, run, company: str, abbr: str, pack: dict):
		"""ERPNext creates "UAE VAT 5%" templates (and excise and zero-rate ones) with the
		company. Make the 5% ones the defaults and list their account in UAE VAT Settings.
		Unregistered: none of that; the not-recoverable account and templates instead."""
		import frappe

		if run.params.get("registration") == "unregistered":
			from erpnext_demo_gen.setup.tax_templates import ensure_not_recoverable

			ensure_not_recoverable(
				run,
				company,
				account_name="VAT Not Recoverable",
				parents=("Indirect Expenses",),
				purchase_title="UAE VAT 5% (not recoverable)",
				description="VAT paid, not recoverable (not registered for VAT)",
				default_rate=5,
				no_tax_title="No VAT (not registered)",
			)
			frappe.db.commit()
			return

		templates = {}
		for doctype in ("Sales Taxes and Charges Template", "Purchase Taxes and Charges Template"):
			name = frappe.db.get_value(doctype, {"company": company, "title": "UAE VAT 5%"})
			if not name:
				frappe.throw(f"{doctype} 'UAE VAT 5%' was not created for {company}")
			templates[doctype] = name
			for other in frappe.get_all(doctype, filters={"company": company, "is_default": 1, "name": ["!=", name]}, pluck="name"):
				frappe.db.set_value(doctype, other, "is_default", 0)
			frappe.db.set_value(doctype, name, "is_default", 1)
		accounts = sorted(
			{
				t.account_head
				for t in frappe.get_all(
					"Sales Taxes and Charges",
					filters={"parent": templates["Sales Taxes and Charges Template"], "parenttype": "Sales Taxes and Charges Template"},
					fields=["account_head"],
				)
			}
		)
		if not frappe.db.exists("UAE VAT Settings", company):
			run.ensure(
				"setup:ae:vat-settings",
				lambda: frappe.get_doc(
					{"doctype": "UAE VAT Settings", "company": company, "uae_vat_accounts": [{"account": a} for a in accounts]}
				).insert(ignore_permissions=True),
			)
		run.update_params(
			ae_vat={
				"sales": templates["Sales Taxes and Charges Template"],
				"purchase": templates["Purchase Taxes and Charges Template"],
				"accounts": accounts,
			}
		)
		frappe.db.commit()

	# ---------------------------------------------------------- writing documents
	def writer_context(self, run, company: str) -> dict:
		import frappe
		from frappe.utils.nestedset import get_root_of

		return {
			"territory": "United Arab Emirates" if frappe.db.exists("Territory", "United Arab Emirates") else get_root_of("Territory"),
			"tax_templates": {},
			"locale_data": {
				"home_emirate": run.params.home_state,
				**(run.params.get("ae_vat") or {}),
				"not_recoverable": run.params.get("not_recoverable") or {},
			},
		}

	def party_fields(self, p, w) -> dict:
		address = p.get("address") or {}
		fields = {}
		if p.get("tax_id"):
			fields["tax_id"] = p.tax_id
		if address:
			fields.update(
				{
					"address_line1": address["address_line1"],
					"address_line2": address.get("address_line2"),
					"city": address["city"],
					"state": address["state"],
					"country": "United Arab Emirates",
				}
			)
		return fields

	def item_fields(self, p, w) -> dict:
		return {}

	def purchase_taxes(self, doc, w):
		if w.tax_registered:
			doc.taxes_and_charges = w.locale_data["purchase"]
			return
		import frappe

		# unregistered: a registered supplier's VAT is a cost; an unregistered one charges none
		nr = w.locale_data["not_recoverable"]
		registered = frappe.db.get_value("Supplier", doc.supplier, "tax_id")
		doc.taxes_and_charges = nr["purchase"] if registered else nr["no_tax_purchase"]

	def sales_taxes(self, doc, w):
		if w.tax_registered:
			doc.taxes_and_charges = w.locale_data["sales"]
		else:  # an empty template, so ERPNext does not apply the company's default VAT one
			doc.taxes_and_charges = w.locale_data["not_recoverable"]["no_tax_sales"]

	def finish_purchase_invoice(self, doc, w) -> bool:
		"""Record the bill's VAT as recoverable (VAT 201 box 9); True when changed."""
		if not w.tax_registered:
			return False
		if doc.meta.has_field("recoverable_standard_rated_expenses") and doc.total_taxes_and_charges:
			doc.recoverable_standard_rated_expenses = doc.total_taxes_and_charges
			return True
		return False

	# ---------------------------------------------------------- install parameters
	required_apps = ("erpnext",)
	unregistered_warning = (
		"generating without VAT: the company is not registered, so sales carry no VAT and the VAT "
		"paid on purchases becomes part of their cost. This demo's turnover is above the mandatory "
		"registration threshold (AED 375,000 of taxable supplies in 12 months), so a real business "
		"like it would have to register"
	)

	def check_options(self, unregistered: bool):
		"""--unregistered is supported (DEC-36)."""

	def resolve_region(self, text: str) -> str | None:
		value = text.strip()
		by_name = {squash(e): e for e in CITIES}
		return EMIRATE_CODES.get(value.upper()) or by_name.get(squash(value))

	def region_choices(self) -> str:
		return ", ".join(f"{code} ({name})" for code, name in EMIRATE_CODES.items())

	def validate_pack(self, pack: dict, check):
		state = (pack.get("company") or {}).get("home_state")
		check(state in CITIES, "company.home_state", f"must be an emirate: {', '.join(CITIES)}")
		rate = (pack.get("vat") or {}).get("rate")
		check(rate == 5, "vat.rate", "UAE VAT is 5%")
		mix = (pack.get("behavior") or {}).get("vat_registration") or {}
		check(mix and set(mix) <= {"registered", "unregistered"} and abs(sum(mix.values()) - 1) < 1e-6,
			"behavior.vat_registration", "needs registered and unregistered shares adding up to 1")
		banking = pack.get("banking") or {}
		for role in ("main", "collection"):
			bank = banking.get(role) or {}
			code = str(bank.get("bank_code") or "")
			check(len(code) == 3 and code.isdigit(), f"banking.{role}.bank_code", "must be 3 digits (IBAN bank code)")
			swift = str(bank.get("swift") or "")
			check(len(swift) in (8, 11) and swift.isalnum(), f"banking.{role}.swift", "must be an 8 or 11 character SWIFT code")

	# ---------------------------------------------------------- verify
	def tax_checks(self, ctx) -> list:
		"""UAE: every sale carries 5% VAT and its VAT Emirate; every bill records its VAT as
		recoverable; the UAE VAT 201 report's boxes 1 (output VAT) and 9 (recoverable input
		VAT) agree with the invoices. Unregistered: no VAT on sales, purchase VAT not
		recoverable; VAT 201 does not apply."""
		if ctx.run.params.get("registration") == "unregistered":
			return self.unregistered_checks(ctx, "VAT")
		import frappe
		from erpnext.regional.report.uae_vat_201.uae_vat_201 import execute as vat_201
		from frappe.utils import flt

		from erpnext_demo_gen.verify import TOLERANCE, Check

		sales = frappe.db.sql(
			"""select name, total_taxes_and_charges tax, base_total_taxes_and_charges base_tax, ifnull(vat_emirate, '') emirate
			from `tabSales Invoice` where company = %s and docstatus = 1""",
			ctx.company,
			as_dict=True,
		)
		untaxed = [s.name for s in sales if flt(s.tax) == 0]
		no_emirate = [s.name for s in sales if not s.emirate]
		sales_check = Check(
			"sales carry 5% VAT and their VAT Emirate",
			bool(sales) and not (untaxed or no_emirate),
			f"{len(sales)} invoices"
			+ (f"; without VAT: {untaxed[:5]}" if untaxed else "")
			+ (f"; without VAT Emirate: {no_emirate[:5]}" if no_emirate else ""),
		)
		bills = frappe.db.sql(
			"""select name, base_total_taxes_and_charges tax, ifnull(recoverable_standard_rated_expenses, 0) recoverable
			from `tabPurchase Invoice` where company = %s and docstatus = 1""",
			ctx.company,
			as_dict=True,
		)
		unrecorded = [b.name for b in bills if abs(flt(b.tax) - flt(b.recoverable)) > TOLERANCE]
		bills_check = Check(
			"bills record their VAT as recoverable",
			bool(bills) and not unrecorded,
			f"{len(bills)} bills" + (f"; recoverable VAT differs: {unrecorded[:5]}" if unrecorded else ""),
		)
		result = vat_201({"company": ctx.company, "from_date": ctx.start, "to_date": ctx.end})
		rows = result[1]
		box1 = sum(flt(r.get("vat_amount")) for r in rows if str(r.get("no", "")).startswith("1"))
		box9 = sum(flt(r.get("vat_amount")) for r in rows if str(r.get("no", "")) == "9")
		sales_vat = sum(flt(s.base_tax) for s in sales)
		input_vat = sum(flt(b.recoverable) for b in bills)
		report = Check(
			"UAE VAT 201 matches the invoices (box 1 output VAT, box 9 recoverable VAT)",
			abs(box1 - sales_vat) <= TOLERANCE * 10 and abs(box9 - input_vat) <= TOLERANCE * 10,
			f"box 1 {box1:,.2f} vs invoices {sales_vat:,.2f}; box 9 {box9:,.2f} vs bills {input_vat:,.2f}",
		)
		return [sales_check, bills_check, report]
