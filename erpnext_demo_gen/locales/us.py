"""United States: a single-state Texas business selling only in Texas (design 5.14, DEC-28).

Sales tax is one combined state + local rate (pack: sales_tax.rate, 8.25%), charged on
every taxable sale: Texas sources in-state sales to the seller's place of business,
so delivered sales carry the store's rate too. No input credit exists:

    stock bought for resale     no tax (resale certificate)  purchase template "TX Resale Purchase"
                                (per bill, not per item: ERPNext copies an item tax template's
                                accounts onto sales documents too, F-45)
    food (water, coffee, ...)   exempt everywhere              Item Tax Template "TX Exempt - Food"
    own-use purchases           tax charged by Texas sellers ("TX Tax Charged"), or use tax
                                owed by the buyer on out-of-state purchases ("TX Use Tax":
                                Add to expense, Deduct to the payable)
    reseller customers          no tax (their resale certificate on file)  "TX Exempt Sale"

Rates are fixed pack data, never fetched (same seed, same data; offline). General
information, not tax advice; details marked *verify* in the design doc.
"""

import random

from erpnext_demo_gen.locales import Locale
from erpnext_demo_gen.naming import slug
from erpnext_demo_gen.planner import weighted

# state -> [(city, first three ZIP digits)]; Texas for the company and its customers,
# other states for out-of-state suppliers (furniture hubs and big markets)
CITIES = {
	"Texas": [
		("Austin", 787),
		("Dallas", 752),
		("Houston", 770),
		("San Antonio", 782),
		("Fort Worth", 761),
		("Plano", 750),
		("Round Rock", 786),
		("Waco", 767),
		("Arlington", 760),
		("Corpus Christi", 784),
		("Lubbock", 794),
		("El Paso", 799),
	],
	"North Carolina": [("High Point", 272), ("Hickory", 286), ("Charlotte", 282)],
	"Michigan": [("Grand Rapids", 495), ("Holland", 494)],
	"Mississippi": [("Tupelo", 388), ("Jackson", 392)],
	"California": [("Los Angeles", 900), ("San Diego", 921)],
	"Georgia": [("Atlanta", 303), ("Dalton", 307)],
	"Illinois": [("Chicago", 606)],
	"Oklahoma": [("Oklahoma City", 731), ("Tulsa", 741)],
}
STATE_CODES = {
	"Texas": "TX",
	"North Carolina": "NC",
	"Michigan": "MI",
	"Mississippi": "MS",
	"California": "CA",
	"Georgia": "GA",
	"Illinois": "IL",
	"Oklahoma": "OK",
}
STREETS = [
	"Main Street",
	"Oak Avenue",
	"Elm Street",
	"Commerce Street",
	"Lamar Boulevard",
	"Congress Avenue",
	"Industrial Parkway",
	"Pecan Street",
	"Cedar Lane",
	"Market Street",
	"Westheimer Road",
	"Riverside Drive",
	"Park Place",
	"Hillcrest Road",
	"Lakeview Drive",
	"Mesa Drive",
]
FIRST_NAMES = [
	"James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "David", "Elizabeth",
	"William", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Carlos", "Maria",
	"Daniel", "Karen", "Matthew", "Nancy", "Anthony", "Lisa", "Mark", "Betty", "Luis", "Sandra",
	"Steven", "Ashley", "Andrew", "Emily", "Joshua", "Michelle", "Kevin", "Amanda", "Brian", "Melissa",
	"Jose", "Rosa", "Kenneth", "Laura", "Ryan", "Rachel", "Jacob", "Hannah", "Tyler", "Grace",
]
LAST_NAMES = [
	"Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
	"Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
	"Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
	"Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
	"Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts",
]
BRAND_WORDS = [
	"Lone Star", "Bluebonnet", "Pecan", "Live Oak", "Cypress", "Mesquite", "Prairie", "Cedar", "Magnolia",
	"Sycamore", "Red River", "Hill Country", "Gulf Coast", "Brazos", "Pinewood", "Willow", "Canyon", "Maple",
]
PLACE_WORDS = ["Ridge", "Creek", "Hollow", "Trail", "Crossing", "Point", "Grove", "Bend", "Valley", "Springs"]
LEGAL_SUFFIXES = ["LLC", "Inc"]

TAX_CLASSES = ("resale", "taxable", "food", "manufacturing")
TAX_CATEGORY_RESELLER = "Reseller"
TAX_CATEGORY_OUT_OF_STATE = "Out of State"
# Item Tax Templates by tax class: which tax accounts they zero ("purchase" = the accounts
# a supplier's bill uses; "all" = sales too)
EXEMPT_TEMPLATES = {
	"manufacturing": ("TX Exempt - Manufacturing", "purchase"),
	"food": ("TX Exempt - Food", "all"),
}
# role -> (account name, root type)
TAX_ACCOUNTS = {
	"sales_tax_payable": ("Texas Sales Tax Payable", "Liability"),
	"use_tax_payable": ("Texas Use Tax Payable", "Liability"),
	"sales_tax_expense": ("Sales Tax Paid", "Expense"),
	"use_tax_expense": ("Use Tax Expense", "Expense"),
}


def routing_number(rng: random.Random, prefix: str) -> str:
	"""A 9-digit ABA routing number with a valid check digit (made up)."""
	digits = prefix + "".join(str(rng.randint(0, 9)) for _ in range(8 - len(prefix)))
	weights = (3, 7, 1, 3, 7, 1, 3, 7)
	total = sum(int(d) * w for d, w in zip(digits, weights, strict=True))
	return digits + str((10 - total % 10) % 10)


class USLocale(Locale):
	code = "US"
	country = "United States"
	aliases = ("USA", "United States of America", "America")

	# ---------------------------------------------------------- planning (pure)
	season_start_month = 1  # seasonality index 0 = January, the fiscal year start

	def regions(self) -> list[str]:
		return sorted(CITIES)

	def person(self, rng: random.Random, region: str) -> tuple[str, str]:
		return rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)

	def business_name(self, rng: random.Random, nouns: list[str]) -> str:
		return f"{rng.choice(BRAND_WORDS)} {rng.choice(PLACE_WORDS)} {rng.choice(nouns)} {rng.choice(LEGAL_SUFFIXES)}"

	def company_name(self, rng: random.Random, nouns: list[str]) -> str:
		return f"{rng.choice(BRAND_WORDS)} {rng.choice(PLACE_WORDS)} {rng.choice(nouns)} {self.company_suffix}"

	def phone(self, rng: random.Random) -> str:
		# 555-01xx numbers are reserved for fiction
		return f"+1-{rng.choice(['512', '214', '713', '210', '817'])}-555-01{rng.randint(0, 99):02d}"

	def address(self, rng: random.Random, region: str) -> dict:
		city, prefix = rng.choice(CITIES[region])
		return {
			"address_line1": f"{rng.randint(100, 9899)} {rng.choice(STREETS)}",
			"city": city,
			"state": region,
			"pincode": f"{prefix}{rng.randint(1, 99):02d}",
			"country": "United States",
		}

	def business_tax(self, rng: random.Random, name: str, region: str, registered: bool, category: str) -> dict:
		"""Every business has an EIN; a reseller also a Texas resale certificate (its
		11-digit Texas taxpayer number), which the shop keeps on file."""
		ein = f"{rng.randint(10, 88):02d}-{rng.randint(0, 9999999):07d}"
		out = {"tax_id": ein, "tax_category": TAX_CATEGORY_RESELLER if category == TAX_CATEGORY_RESELLER else None}
		if category == TAX_CATEGORY_RESELLER:
			out["resale_certificate"] = f"3{rng.randint(0, 9999999999):010d}"
		return out

	def individual_tax(self) -> dict:
		return {}

	def customer_category(self, rng: random.Random, behavior: dict, sales_tax: bool) -> tuple[bool, str]:
		category = weighted(rng, behavior["tax_categories"])
		return True, TAX_CATEGORY_RESELLER if category == "reseller" else "Regular"

	def customer_home_share(self, behavior: dict, sales_tax: bool) -> float:
		return 1.0  # sells only in Texas (out-of-state sales would need registration there)

	def item_tax(self, family: dict, pack: dict) -> dict:
		tax_class = family.get("tax_class", "resale")
		rate = 0.0 if tax_class == "food" else float(pack["sales_tax"]["rate"])
		return {"tax_class": tax_class, "tax_rate": rate}

	def item_tax_rate(self, item_params: dict) -> float:
		return item_params["tax_rate"]

	def purchase_tax_rate(self, item_params: dict) -> float:
		return 0.0 if item_params["tax_class"] in ("resale", "manufacturing", "food") else item_params["tax_rate"]

	prices_include_tax = False  # US shelf prices are before sales tax

	# ---------------------------------------------------------- payments
	payment_modes = ("Cash", "Check", "ACH", "Wire Transfer", "Card")
	counter_modes = ("Card",)  # the card terminal settles into the collection account

	def payment_reference(self, rng: random.Random, mode: str, amount: float, when, bank: dict, banking: dict) -> str:
		if mode == "Check":
			return f"{rng.randint(1001, 9999)}"
		if mode == "ACH":  # trace number: the bank's routing prefix and a sequence
			return f"{bank['routing_prefix']}{rng.randint(10**10, 10**11 - 1)}"
		if mode == "Wire Transfer":  # Fedwire IMAD: date, source, sequence
			return f"{when:%Y%m%d}MMQFMP{rng.randint(100000, 999999)}"
		return f"AUTH{rng.randint(100000, 999999)}"  # card authorization code

	def sweep_reference(self, rng: random.Random, source: str, when, banking: dict) -> str:
		if source == "collection":
			return f"XFER{when:%y%m%d}{rng.randint(1000, 9999)}"
		return f"DEP{when:%y%m%d}{rng.randint(100, 999)}"  # cash deposit slip

	# ---------------------------------------------------------- setup
	currency = "USD"
	company_suffix = "LLC"
	timezone = "America/Chicago"

	def company_fields(self, params) -> dict:
		return {"country": "United States", "default_currency": "USD", "chart_of_accounts": "Standard"}

	def wants_company_address(self, params) -> bool:
		return True

	def company_address(self, rng: random.Random, company: str, region: str, wizard: bool) -> dict:
		return {"address_title": company, "address_type": "Billing", **self.address(rng, region)}

	def fiscal_year_starts(self, start, end) -> list:
		from datetime import date

		return [date(y, 1, 1) for y in range(start.year, end.year + 1)]

	def fiscal_year_end(self, fy_start):
		from datetime import date

		return date(fy_start.year, 12, 31)

	def bank_account_fields(self, rng: random.Random, bank: dict) -> dict:
		return {
			"bank_account_no": "".join(str(rng.randint(0, 9)) for _ in range(10)),
			"branch_code": routing_number(rng, bank["routing_prefix"]),
		}

	def setup_taxes(self, run, company: str, abbr: str, pack: dict):
		"""Texas sales and use tax: accounts, exempt Item Tax Templates, sales and purchase
		templates, the Reseller and Out of State tax categories and their Tax Rules.
		Everything goes through the registry, so uninstall removes it."""
		import frappe

		rate = float(pack["sales_tax"]["rate"])
		accounts = {}
		for role, (name, root) in TAX_ACCOUNTS.items():
			parent = _parent_account(company, root)

			def create(name=name, root=root, parent=parent):
				return frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": name,
						"company": company,
						"parent_account": parent,
						"account_type": "Tax",
						"account_currency": "USD",
					}
				).insert(ignore_permissions=True)

			existing = frappe.db.get_value("Account", {"company": company, "account_name": name})
			accounts[role] = existing or run.ensure(f"setup:us:account:{role}", create)

		for category in (TAX_CATEGORY_RESELLER, TAX_CATEGORY_OUT_OF_STATE):
			if not frappe.db.exists("Tax Category", category):
				run.ensure(
					f"setup:us:tax-category:{category}",
					lambda c=category: frappe.get_doc({"doctype": "Tax Category", "title": c}).insert(ignore_permissions=True),
				)

		purchase_accounts = ("sales_tax_expense", "use_tax_expense", "use_tax_payable")
		for tax_class, (title, scope) in EXEMPT_TEMPLATES.items():
			roles = purchase_accounts if scope == "purchase" else tuple(TAX_ACCOUNTS)
			run.ensure(
				f"setup:us:item-tax-template:{tax_class}",
				lambda title=title, roles=roles: frappe.get_doc(
					{
						"doctype": "Item Tax Template",
						"title": title,
						"company": company,
						"taxes": [{"tax_type": accounts[r], "tax_rate": 0} for r in roles],
					}
				).insert(ignore_permissions=True),
			)

		label = f"{rate:g}%"
		sales = run.ensure(
			"setup:us:sales-template",
			lambda: frappe.get_doc(
				{
					"doctype": "Sales Taxes and Charges Template",
					"title": f"TX Sales Tax {label}",
					"company": company,
					"is_default": 1,
					"taxes": [
						{
							"charge_type": "On Net Total",
							"account_head": accounts["sales_tax_payable"],
							"rate": rate,
							"description": f"Texas sales tax {label} (state 6.25% + local)",
						}
					],
				}
			).insert(ignore_permissions=True),
		)
		exempt_sale = run.ensure(
			"setup:us:sales-template:exempt",
			lambda: frappe.get_doc(
				{
					"doctype": "Sales Taxes and Charges Template",
					"title": "TX Exempt Sale",
					"company": company,
					"tax_category": TAX_CATEGORY_RESELLER,
					"taxes": [],
				}
			).insert(ignore_permissions=True),
		)
		charged = run.ensure(
			"setup:us:purchase-template",
			lambda: frappe.get_doc(
				{
					"doctype": "Purchase Taxes and Charges Template",
					"title": f"TX Tax Charged {label}",
					"company": company,
					"is_default": 1,
					"taxes": [
						{
							"category": "Total",
							"add_deduct_tax": "Add",
							"charge_type": "On Net Total",
							"account_head": accounts["sales_tax_expense"],
							"rate": rate,
							"description": f"Texas sales tax charged by the seller {label}",
						}
					],
				}
			).insert(ignore_permissions=True),
		)
		resale_purchase = run.ensure(
			"setup:us:purchase-template:resale",
			lambda: frappe.get_doc(
				{
					"doctype": "Purchase Taxes and Charges Template",
					"title": "TX Resale Purchase (certificate)",
					"company": company,
					"taxes": [],
				}
			).insert(ignore_permissions=True),
		)
		use_tax = run.ensure(
			"setup:us:purchase-template:use-tax",
			lambda: frappe.get_doc(
				{
					"doctype": "Purchase Taxes and Charges Template",
					"title": f"TX Use Tax {label}",
					"company": company,
					"tax_category": TAX_CATEGORY_OUT_OF_STATE,
					"taxes": [
						{
							"category": "Total",
							"add_deduct_tax": "Add",
							"charge_type": "On Net Total",
							"account_head": accounts["use_tax_expense"],
							"rate": rate,
							"description": f"Texas use tax {label} (seller charged none)",
						},
						{
							"category": "Total",
							"add_deduct_tax": "Deduct",
							"charge_type": "On Net Total",
							"account_head": accounts["use_tax_payable"],
							"rate": rate,
							"description": "Texas use tax payable",
						},
					],
				}
			).insert(ignore_permissions=True),
		)
		# ERPNext's own US templates (from country_wise_tax.json) stay, but not as defaults
		for doctype, keep in (("Sales Taxes and Charges Template", sales), ("Purchase Taxes and Charges Template", charged)):
			for other in frappe.get_all(doctype, filters={"company": company, "is_default": 1, "name": ["!=", keep]}, pluck="name"):
				frappe.db.set_value(doctype, other, "is_default", 0)

		# Tax Rules, so documents a user creates by hand get the same templates
		for key, values in (
			("sales-reseller", {"tax_type": "Sales", "sales_tax_template": exempt_sale, "tax_category": TAX_CATEGORY_RESELLER}),
			("purchase-out-of-state", {"tax_type": "Purchase", "purchase_tax_template": use_tax, "tax_category": TAX_CATEGORY_OUT_OF_STATE}),
		):
			run.ensure(
				f"setup:us:tax-rule:{key}",
				lambda values=values: frappe.get_doc(
					{"doctype": "Tax Rule", "company": company, "priority": 1, **values}
				).insert(ignore_permissions=True),
			)
		run.update_params(
			us_tax={
				"sales": sales,
				"exempt_sale": exempt_sale,
				"purchase": charged,
				"resale_purchase": resale_purchase,
				"use_tax": use_tax,
				"accounts": accounts,
			}
		)
		frappe.db.commit()

	# ---------------------------------------------------------- writing documents
	def writer_context(self, run, company: str) -> dict:
		import frappe
		from frappe.utils.nestedset import get_root_of

		templates = {}
		for tax_class, (title, _scope) in EXEMPT_TEMPLATES.items():
			name = frappe.db.get_value("Item Tax Template", {"company": company, "title": title})
			if name:
				templates[tax_class] = name
		return {
			"territory": "United States" if frappe.db.exists("Territory", "United States") else get_root_of("Territory"),
			"tax_templates": templates,
			"locale_data": {"home_state": run.params.home_state, **(run.params.get("us_tax") or {})},
		}

	def party_fields(self, p, w) -> dict:
		"""EIN, tax category (Reseller; Out of State for suppliers elsewhere), and ERPNext's
		quick-entry address fields (its after_insert creates the primary address). A
		reseller's certificate number goes into the party's details."""
		address = p.get("address") or {}
		fields = {}
		if p.get("tax_id"):
			fields["tax_id"] = p.tax_id
		category = p.get("tax_category")
		if not category and address and address["state"] != w.locale_data["home_state"]:
			category = TAX_CATEGORY_OUT_OF_STATE
		if category:
			fields["tax_category"] = category
		if p.get("resale_certificate"):
			fields["customer_details"] = f"Texas resale certificate on file: {p.resale_certificate}"
		if address:
			fields.update(
				{
					"address_line1": address["address_line1"],
					"city": address["city"],
					"state": address["state"],
					"pincode": address["pincode"],
					"country": "United States",
				}
			)
		return fields

	def item_fields(self, p, w) -> dict:
		template = w.tax_templates.get(p.tax_class)
		return {"taxes": [{"item_tax_template": template}]} if template else {}

	def purchase_taxes(self, doc, w):
		"""Stock for resale: no tax (the store's resale certificate). Own-use purchases:
		use tax from an out-of-state supplier (the seller charges none), else the Texas
		seller's tax. Exempt lines (food) stay at 0 through their Item Tax Template."""
		import frappe

		data = w.locale_data
		codes = {row.item_code for row in doc.items}
		if codes and all(frappe.db.get_value("Item", c, "is_sales_item") for c in codes):
			doc.taxes_and_charges = data["resale_purchase"]
			return
		category = frappe.db.get_value("Supplier", doc.supplier, "tax_category")
		doc.taxes_and_charges = data["use_tax"] if category == TAX_CATEGORY_OUT_OF_STATE else data["purchase"]

	def sales_taxes(self, doc, w):
		import frappe

		customer = doc.get("customer") or doc.get("party_name")
		category = frappe.db.get_value("Customer", customer, "tax_category")
		data = w.locale_data
		doc.taxes_and_charges = data["exempt_sale"] if category == TAX_CATEGORY_RESELLER else data["sales"]

	# ---------------------------------------------------------- install parameters
	required_apps = ("erpnext",)

	def resolve_region(self, text: str) -> str | None:
		value = text.strip()
		by_code = {code: state for state, code in STATE_CODES.items()}
		by_name = {slug(state): state for state in CITIES}
		return by_code.get(value.upper()) or by_name.get(slug(value))

	def region_choices(self) -> str:
		return "TX (Texas)"

	def home_regions(self) -> list[str]:
		return ["Texas"]  # single-state scope (design 5.14)

	def check_options(self, unregistered: bool, fictitious_id: bool):
		from erpnext_demo_gen.service import DemoDataError

		if unregistered or fictitious_id:
			raise DemoDataError("--no-gst and --fictitious-gstin are for India packs")

	def check_wizard_company(self, company: str, params: dict, home_region: str | None, unregistered: bool, fictitious_id: bool):
		params["home_state"] = home_region or "Texas"

	def validate_pack(self, pack: dict, check):
		state = (pack.get("company") or {}).get("home_state")
		check(state in self.home_regions(), "company.home_state", f"must be one of {', '.join(self.home_regions())}")
		rate = (pack.get("sales_tax") or {}).get("rate")
		check(isinstance(rate, (int, float)) and 0 < rate < 20, "sales_tax.rate", "must be a percentage, e.g. 8.25")
		for i, f in enumerate((pack.get("catalog") or {}).get("families") or []):
			cls = f.get("tax_class", "resale")
			check(cls in TAX_CLASSES, f"catalog.families[{i}].tax_class", f"must be one of {', '.join(TAX_CLASSES)}")
		mix = (pack.get("behavior") or {}).get("tax_categories") or {}
		check(mix and set(mix) <= {"regular", "reseller"} and abs(sum(mix.values()) - 1) < 1e-6,
			"behavior.tax_categories", "needs regular and reseller shares adding up to 1")
		banking = pack.get("banking") or {}
		for role in ("main", "collection"):
			prefix = str((banking.get(role) or {}).get("routing_prefix") or "")
			check(len(prefix) == 4 and prefix.isdigit(), f"banking.{role}.routing_prefix", "must be 4 digits")

	# ---------------------------------------------------------- verify
	def tax_checks(self, ctx) -> list:
		"""Texas (design 5.14): regular customers pay the sales tax, resellers with a
		certificate on file pay none, deliveries ship to Texas, stock for resale is bought
		tax-free."""
		import frappe
		from frappe.utils import flt

		from erpnext_demo_gen.locales.us import TAX_CATEGORY_RESELLER
		from erpnext_demo_gen.verify import Check

		sales = frappe.db.sql(
			"""select d.name, d.customer, ifnull(c.tax_category, '') category, ifnull(c.customer_details, '') details,
				d.total_taxes_and_charges tax
			from `tabSales Invoice` d join `tabCustomer` c on c.name = d.customer
			where d.company = %s and d.docstatus = 1 and d.is_return = 0""",
			ctx.company,
			as_dict=True,
		)
		untaxed = [s.name for s in sales if s.category != TAX_CATEGORY_RESELLER and flt(s.tax) <= 0]
		taxed_resale = [s.name for s in sales if s.category == TAX_CATEGORY_RESELLER and flt(s.tax) != 0]
		no_certificate = sorted({s.customer for s in sales if flt(s.tax) == 0 and "resale certificate" not in s.details})
		resellers = sum(s.category == TAX_CATEGORY_RESELLER for s in sales)
		sales_check = Check(
			"sales tax: regular customers taxed, resellers exempt with a certificate",
			not (untaxed or taxed_resale or no_certificate),
			f"{len(sales) - resellers} taxed, {resellers} to resellers"
			+ (f"; untaxed: {untaxed[:5]}" if untaxed else "")
			+ (f"; taxed resale: {taxed_resale[:5]}" if taxed_resale else "")
			+ (f"; no certificate: {no_certificate[:5]}" if no_certificate else ""),
		)
		outside = frappe.db.sql_list(
			"""select dn.name from `tabDelivery Note` dn left join `tabAddress` a on a.name = dn.shipping_address_name
			where dn.company = %s and dn.docstatus = 1 and ifnull(a.state, '') != 'Texas'""",
			ctx.company,
		)
		shipping = Check("deliveries ship to Texas addresses", not outside, f"outside Texas: {outside[:5]}" if outside else "")
		resale_taxed = frappe.db.sql_list(
			"""select pi.name from `tabPurchase Invoice` pi
			where pi.company = %s and pi.docstatus = 1 and pi.total_taxes_and_charges != 0
			and not exists (select 1 from `tabPurchase Invoice Item` i join `tabItem` it on it.name = i.item_code
				where i.parent = pi.name and it.is_sales_item = 0)""",
			ctx.company,
		)
		purchases = Check(
			"stock for resale bought tax-free (resale certificate)",
			not resale_taxed,
			f"resale bills with tax: {resale_taxed[:5]}" if resale_taxed else "",
		)
		return [sales_check, shipping, purchases]


def _parent_account(company: str, root_type: str) -> str:
	"""Duties and Taxes for the payables, Indirect Expenses for the expense accounts."""
	import frappe

	preferred = "Duties and Taxes" if root_type == "Liability" else "Indirect Expenses"
	return frappe.db.get_value(
		"Account", {"company": company, "account_name": preferred, "is_group": 1}
	) or frappe.db.get_value("Account", {"company": company, "root_type": root_type, "is_group": 1}, order_by="lft desc")
