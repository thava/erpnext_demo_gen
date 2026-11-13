"""Germany: 19% / 7% VAT (Umsatzsteuer) with input credit, SKR04 chart, Bundesländer, EUR.

What a VAT-registered German trading business (GmbH) looks like in ERPNext's own German
set-up (country_wise_tax.json for the "SKR04 mit Kontonummern" chart):

    chart       SKR04, the DATEV chart most GmbHs use; ERPNext creates its tax
                templates with the company
    sales       "Lieferung oder sonstige Leistung im Inland": rows for Umsatzsteuer 19 %
                and 7 % at rate 0; each item's Item Tax Template ("19 %", "7 %") sets
                the rate, so one invoice can mix both rates
    purchases   "Lieferung aus dem Inland": Abziehbare Vorsteuer 19 % / 7 % the same
                way; input VAT is fully deductible
    prices      consumer prices include VAT (Preisangabenverordnung)
    return      the monthly VAT return (UStVA) is output VAT minus input VAT

Kleinunternehmer (--unregistered; § 19 UStG, limits since 2025: previous year's net
turnover <= EUR 25,000 and current year's <= EUR 100,000): sales carry no VAT, income goes
to SKR04's "Erlöse aus Kleinunternehmer", and every invoice carries the § 19 note (Terms
and Conditions); the company has no USt-IdNr. (its Steuernummer is not modelled). VAT paid
on purchases cannot be deducted: "Valuation and Total" rows on a "Nicht abziehbare
Vorsteuer" expense account, at each item's rate (in the cost of stock items, DEC-37).

Furniture is 19%; staff coffee is food at 7%; bottled water is 19% (only tap water
is reduced). Out of scope for the demo: EU and non-EU trade (reverse charge,
innergemeinschaftlicher Erwerb), Kleinunternehmer suppliers, § 13b construction
services, DATEV export, e-invoicing (XRechnung / ZUGFeRD). General information, not
tax advice.
"""

import random

from erpnext_demo_gen.locales import Locale, squash
from erpnext_demo_gen.planner import weighted
from erpnext_demo_gen.compat import append_template_taxes

CHART = "SKR04 mit Kontonummern"

# Bundesland -> cities with a postcode (PLZ) to start from
CITIES = {
	"Bayern": {"München": 80331, "Nürnberg": 90402, "Augsburg": 86150, "Regensburg": 93047, "Ingolstadt": 85049},
	"Baden-Württemberg": {"Stuttgart": 70173, "Karlsruhe": 76131, "Mannheim": 68159, "Freiburg im Breisgau": 79098},
	"Nordrhein-Westfalen": {"Köln": 50667, "Düsseldorf": 40213, "Dortmund": 44135, "Bielefeld": 33602, "Herford": 32052},
	"Hessen": {"Frankfurt am Main": 60311, "Wiesbaden": 65183, "Kassel": 34117, "Darmstadt": 64283},
	"Niedersachsen": {"Hannover": 30159, "Braunschweig": 38100, "Osnabrück": 49074},
	"Berlin": {"Berlin": 10115},
	"Hamburg": {"Hamburg": 20095},
	"Sachsen": {"Leipzig": 4109, "Dresden": 1067, "Chemnitz": 9111},
	"Rheinland-Pfalz": {"Mainz": 55116, "Koblenz": 56068},
	"Schleswig-Holstein": {"Kiel": 24103, "Lübeck": 23552},
}
STATE_CODES = {  # ISO 3166-2:DE
	"BY": "Bayern", "BW": "Baden-Württemberg", "NW": "Nordrhein-Westfalen", "HE": "Hessen", "NI": "Niedersachsen",
	"BE": "Berlin", "HH": "Hamburg", "SN": "Sachsen", "RP": "Rheinland-Pfalz", "SH": "Schleswig-Holstein",
}
AREA_CODES = {"München": "89", "Berlin": "30", "Hamburg": "40", "Köln": "221", "Frankfurt am Main": "69", "Stuttgart": "711"}
STREETS = [
	"Hauptstraße", "Bahnhofstraße", "Schillerstraße", "Goethestraße", "Gartenstraße", "Lindenstraße", "Industriestraße",
	"Am Markt", "Kirchweg", "Mühlenweg", "Bergstraße", "Ringstraße", "Gewerbestraße", "Friedrichstraße", "Leopoldstraße",
	"Kaiserstraße", "Wiesenweg", "Schulstraße",
]
FIRST_NAMES = [
	"Lukas", "Anna", "Maximilian", "Sophie", "Felix", "Marie", "Jonas", "Laura", "Leon", "Lena", "Paul", "Julia",
	"Tobias", "Katharina", "Stefan", "Sabine", "Thomas", "Claudia", "Michael", "Andrea", "Mehmet", "Ayşe", "Elif",
	"Nikola", "Anja", "Jan", "Hannah", "Florian", "Miriam", "David",
]
LAST_NAMES = [
	"Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz", "Hoffmann",
	"Schäfer", "Koch", "Bauer", "Richter", "Klein", "Wolf", "Schröder", "Neumann", "Schwarz", "Zimmermann",
	"Braun", "Krüger", "Hofmann", "Hartmann", "Yılmaz", "Kaya", "Nowak", "Lange", "Werner", "Krause",
]
BRAND_WORDS = [
	"Alpen", "Nordlicht", "Eichenhof", "Isar", "Rheinland", "Lindenhof", "Bergland", "Elbe", "Donau", "Waldmann",
	"Hansa", "Sonnenhof", "Maingold", "Kranich", "Holzwerk", "Brunnen", "Stern", "Ahorn", "Birkenwald", "Löwen",
]
LEGAL_SUFFIXES = ["GmbH", "GmbH", "GmbH & Co. KG", "KG", "e.K.", "AG"]


def vat_id(rng: random.Random) -> str:
	"""A German VAT ID (USt-IdNr.) with a valid check digit (made up): DE + 8 digits +
	an ISO 7064 MOD 11,10 check digit."""
	digits = [rng.randint(1, 3)] + [rng.randint(0, 9) for _ in range(7)]
	product = 10
	for d in digits:
		total = (d + product) % 10 or 10
		product = (2 * total) % 11
	check = (11 - product) % 10
	return "DE" + "".join(map(str, digits)) + str(check)


def iban(rng: random.Random, blz: str) -> str:
	"""A German IBAN with valid check digits (made up): DE, 2 check digits, 8-digit BLZ, 10 digits."""
	bban = blz + "".join(str(rng.randint(0, 9)) for _ in range(10))
	digits = "".join(str(int(ch, 36)) for ch in bban + "DE00")
	return f"DE{98 - int(digits) % 97:02d}{bban}"


# Company defaults ERPNext picks wrongly from SKR04 (the first account of each type):
# field -> (wrong pick by account name, SKR04 account to use)
DEFAULT_FIXES = {
	"default_income_account": ("Erlöse aus Kleinunternehmer i. S. d. § 19 Abs. 1 UStG", "Erlöse 19 % USt"),
	"default_receivable_account": ("Erhaltene Anz. auf Bestellungen (Verb.)", "Forderungen aus Lieferungen und Leistungen"),
	"default_payable_account": ("Sonstige Verb.", "Verb. aus Lieferungen und Leistungen"),
	"default_cash_account": ("Nebenkasse 2", "Kasse"),
	"default_expense_account": ("Herstellungskosten", "Wareneingang"),
}
SALES_TEMPLATE = "Lieferung oder sonstige Leistung im Inland"
PURCHASE_TEMPLATE = "Lieferung aus dem Inland"
ITEM_TEMPLATES = {"standard": "19 %", "reduced": "7 %"}  # titles of ERPNext's Item Tax Templates
VAT_CLASSES = tuple(ITEM_TEMPLATES)
KLEINUNTERNEHMER_INCOME = "Erlöse aus Kleinunternehmer i. S. d. § 19 Abs. 1 UStG"  # SKR04 4185
KLEINUNTERNEHMER_TERMS = "Kleinunternehmerregelung (§ 19 UStG)"
KLEINUNTERNEHMER_NOTE = "Gemäß § 19 UStG enthält der ausgewiesene Rechnungsbetrag keine Umsatzsteuer."


class DELocale(Locale):
	code = "DE"
	country = "Germany"
	aliases = ("Deutschland", "GER", "DEU", "BRD")

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
		if rng.random() < 0.4:
			return f"+49-15{rng.choice('1257')}-{rng.randint(1000000, 9999999)}"  # mobile
		return f"+49-{rng.choice(list(AREA_CODES.values()))}-{rng.randint(100000, 9999999)}"

	def address(self, rng: random.Random, region: str) -> dict:
		city = rng.choice(sorted(CITIES[region]))
		return {
			"address_line1": f"{rng.choice(STREETS)} {rng.randint(1, 180)}",
			"city": city,
			"state": region,
			"pincode": f"{CITIES[region][city] + rng.randint(0, 40):05d}",
			"country": "Germany",
		}

	def business_tax(self, rng: random.Random, name: str, region: str, registered: bool, category: str) -> dict:
		return {"tax_id": vat_id(rng) if registered else None, "vat_registered": registered}

	def individual_tax(self) -> dict:
		return {}

	def customer_category(self, rng: random.Random, behavior: dict, sales_tax: bool) -> tuple[bool, str]:
		category = weighted(rng, behavior["vat_registration"])
		return category == "registered", category

	def customer_home_share(self, behavior: dict, sales_tax: bool) -> float:
		return behavior["geography"]["home_state_share"]

	def item_tax(self, family: dict, pack: dict) -> dict:
		vat_class = family.get("vat", "standard")
		return {"vat_class": vat_class, "vat_rate": float(pack["vat"][vat_class])}

	def item_tax_rate(self, item_params: dict) -> float:
		return item_params["vat_rate"]

	prices_include_tax = True  # consumer prices include VAT (PAngV)

	# ---------------------------------------------------------- payments
	payment_modes = ("Cash", "Wire Transfer", "Direct Debit", "Card")  # SEPA transfer, SEPA direct debit, girocard
	counter_modes = ("Card",)  # the card terminal settles into the collection account

	def payment_reference(self, rng: random.Random, mode: str, amount: float, when, bank: dict, banking: dict) -> str:
		if mode == "Wire Transfer":  # SEPA end-to-end reference
			return f"E2E{when:%Y%m%d}{rng.randint(10**7, 10**8 - 1)}"
		if mode == "Direct Debit":  # SEPA mandate reference
			return f"MNDT-{rng.randint(100000, 999999)}"
		return f"{rng.randint(100000, 999999)}"  # card terminal trace number

	def sweep_reference(self, rng: random.Random, source: str, when, banking: dict) -> str:
		if source == "collection":
			return f"UEB{when:%y%m%d}{rng.randint(1000, 9999)}"
		return f"EINZ{when:%y%m%d}{rng.randint(100, 999)}"  # cash deposit (Bareinzahlung)

	# ---------------------------------------------------------- setup
	currency = "EUR"
	company_suffix = "GmbH"
	timezone = "Europe/Berlin"
	wizard_chart = CHART
	funding_accounts = {"share_capital": "Gezeichnetes Kapital", "term_loan": "Verb. gg. Kreditinstituten (1-5 J.)"}

	def company_fields(self, params) -> dict:
		rng = random.Random(f"{params.seed}:company-vat-id")
		fields = {"country": "Germany", "default_currency": "EUR", "chart_of_accounts": CHART}
		if params.get("registration") != "unregistered":
			fields["tax_id"] = vat_id(rng)  # the company's USt-IdNr.
		return fields

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
		number = iban(rng, bank["blz"])
		return {"iban": number, "bank_account_no": number[-10:], "branch_code": bank["bic"]}

	def setup_taxes(self, run, company: str, abbr: str, pack: dict):
		"""ERPNext creates the SKR04 tax templates with the company. Correct the company
		defaults it picks wrongly from SKR04 (only while they are still its wrong pick)
		and remember the templates and VAT accounts. A Kleinunternehmer keeps ERPNext's
		income pick (4185) and gets the non-deductible set-up and the § 19 note."""
		import frappe

		unregistered = run.params.get("registration") == "unregistered"
		fixed = {}
		for field, (wrong, right) in DEFAULT_FIXES.items():
			if unregistered and field == "default_income_account":
				continue
			current = frappe.db.get_value("Company", company, field)
			if current and frappe.db.get_value("Account", current, "account_name") != wrong:
				continue
			account = frappe.db.get_value("Account", {"company": company, "account_name": right, "is_group": 0})
			if account:
				frappe.db.set_value("Company", company, field, account)
				fixed[field] = account

		def template(doctype, title):
			name = frappe.db.get_value(doctype, {"company": company, "title": title})
			if not name:
				frappe.throw(f"{doctype} {title!r} was not created for {company} (needs the {CHART} chart)")
			return name

		sales = template("Sales Taxes and Charges Template", SALES_TEMPLATE)
		purchase = template("Purchase Taxes and Charges Template", PURCHASE_TEMPLATE)

		def accounts(doctype, parent):
			rows = frappe.get_all(doctype, filters={"parent": parent, "parenttype": f"{doctype} Template"}, pluck="account_head")
			return sorted(set(rows))

		run.update_params(
			de_vat={
				"sales": sales,
				"purchase": purchase,
				"output_accounts": accounts("Sales Taxes and Charges", sales),
				"input_accounts": accounts("Purchase Taxes and Charges", purchase),
				"item_templates": {cls: template("Item Tax Template", title) for cls, title in ITEM_TEMPLATES.items()},
				"defaults_fixed": fixed,
			}
		)
		if unregistered:
			self._setup_kleinunternehmer(run, company)
		frappe.db.commit()

	def _setup_kleinunternehmer(self, run, company: str):
		import frappe

		from erpnext_demo_gen.setup.tax_templates import ensure_not_recoverable

		ensure_not_recoverable(
			run,
			company,
			account_name="Nicht abziehbare Vorsteuer (Kleinunternehmer)",
			parents=("7 - sonstige betriebliche Aufwendungen",),
			purchase_title="Lieferung aus dem Inland (Vorsteuer nicht abziehbar)",
			description="Vorsteuer, nicht abziehbar (§ 19 UStG)",
			default_rate=19,
			item_templates={cls: (f"{title} (nicht abziehbar)", float(title.split()[0])) for cls, title in ITEM_TEMPLATES.items()},
			tax_category="Vorsteuer nicht abziehbar",
			no_tax_title="Kleinunternehmer (keine Umsatzsteuer)",
		)
		terms = KLEINUNTERNEHMER_TERMS
		if not frappe.db.exists("Terms and Conditions", terms):  # one the user already has is used as it is
			terms = run.ensure(
				"setup:de:kleinunternehmer-terms",
				lambda: frappe.get_doc(
					{"doctype": "Terms and Conditions", "title": KLEINUNTERNEHMER_TERMS, "terms": KLEINUNTERNEHMER_NOTE, "selling": 1, "buying": 0}
				).insert(ignore_permissions=True),
			)
		income = frappe.db.get_value("Account", {"company": company, "account_name": KLEINUNTERNEHMER_INCOME, "is_group": 0})
		if not income:
			frappe.throw(f"Account {KLEINUNTERNEHMER_INCOME!r} not found for {company} (needs the {CHART} chart)")
		run.update_params(kleinunternehmer={"terms": terms, "income_account": income})

	# ---------------------------------------------------------- writing documents
	def writer_context(self, run, company: str) -> dict:
		import frappe
		from frappe.utils.nestedset import get_root_of

		data = {
			**(run.params.get("de_vat") or {}),
			"not_recoverable": run.params.get("not_recoverable") or {},
			"kleinunternehmer": run.params.get("kleinunternehmer") or {},
		}
		return {
			"territory": "Germany" if frappe.db.exists("Territory", "Germany") else get_root_of("Territory"),
			"tax_templates": data.get("item_templates") or {},
			"locale_data": data,
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
					"city": address["city"],
					"state": address["state"],
					"pincode": address["pincode"],
					"country": "Germany",
				}
			)
		return fields

	def item_fields(self, p, w) -> dict:
		"""The item's VAT rate comes from its Item Tax Template ("19 %" or "7 %"). A
		Kleinunternehmer's items carry only the non-deductible one, under a tax category
		that only purchases use, so sales lines get no VAT rate."""
		vat_class = p.get("vat_class") or "standard"
		if not w.tax_registered:
			nr = w.locale_data["not_recoverable"]
			return {"taxes": [{"item_tax_template": nr["items"][vat_class], "tax_category": nr["tax_category"]}]}
		template = w.tax_templates.get(vat_class)
		return {"taxes": [{"item_tax_template": template}]} if template else {}

	def item_defaults(self, p, w) -> dict:
		if w.tax_registered or not p.get("is_sales_item", 1):
			return {}
		return {"income_account": w.locale_data["kleinunternehmer"]["income_account"]}

	def purchase_taxes(self, doc, w):
		if w.tax_registered:
			self._fill(doc, w.locale_data["purchase"])
			return
		# every supplier charges VAT (an USt-IdNr. is only needed for EU trade; Kleinunternehmer
		# suppliers are out of scope), which a Kleinunternehmer cannot deduct
		nr = w.locale_data["not_recoverable"]
		doc.tax_category = nr["tax_category"]  # picks the items' non-deductible rates
		self._fill(doc, nr["purchase"])

	def sales_taxes(self, doc, w):
		if w.tax_registered:
			self._fill(doc, w.locale_data["sales"])
			return
		# Kleinunternehmer: no VAT (an empty template stops ERPNext's default) and the § 19 note
		doc.taxes_and_charges = w.locale_data["not_recoverable"]["no_tax_sales"]
		doc.set("taxes", [])
		doc.tc_name = w.locale_data["kleinunternehmer"]["terms"]
		doc.terms = KLEINUNTERNEHMER_NOTE

	@staticmethod
	def _fill(doc, template: str):
		"""Set the template and its rows before the first save. ERPNext adds tax rows only
		to a document without any; with "Automatically add Taxes and Charges from Item
		Tax Template" on (its default) it would also add a row for every account of the
		item's template: input VAT, EU and reverse-charge accounts, each at 19% (F-48)."""
		doc.taxes_and_charges = template
		doc.set("taxes", [])
		append_template_taxes(doc)

	# ---------------------------------------------------------- install parameters
	required_apps = ("erpnext",)
	tax_id_means_registered = False  # suppliers without an USt-IdNr. still charge VAT
	unregistered_warning = (
		"generating a Kleinunternehmer (§ 19 UStG): sales carry no VAT and the VAT paid on purchases "
		"becomes part of their cost. This demo's turnover is above the limits (net turnover of at "
		"most EUR 25,000 in the previous year and EUR 100,000 in the current year), so a real business "
		"like it could not use the scheme"
	)

	def check_options(self, unregistered: bool):
		"""--unregistered is supported: a Kleinunternehmer (DEC-36)."""

	def resolve_region(self, text: str) -> str | None:
		value = text.strip()
		by_name = {squash(s): s for s in CITIES}
		by_name.update({"bavaria": "Bayern", "northrhinewestphalia": "Nordrhein-Westfalen", "lowersaxony": "Niedersachsen", "saxony": "Sachsen", "hesse": "Hessen"})
		return STATE_CODES.get(value.upper()) or by_name.get(squash(value))

	def region_choices(self) -> str:
		return ", ".join(f"{code} ({name})" for code, name in STATE_CODES.items())

	def registration_lines(self, run, company: str) -> list[str]:
		"""USt-IdNr. (the Tax ID) and a Steuernummer in Bavaria's format (FFF/BBB/UUUUP);
		a Kleinunternehmer has the Steuernummer only."""
		import frappe

		rng = random.Random(f"{run.params.seed}:company-steuernummer")
		steuernummer = f"{rng.randint(100, 199)}/{rng.randint(100, 999)}/{rng.randint(10000, 99999)}"
		if run.params.get("registration") == "unregistered":
			return ["Kleinunternehmer (§ 19 UStG): no USt-IdNr., no VAT on invoices", f"Steuernummer {steuernummer}"]
		vat_id = frappe.db.get_value("Company", company, "tax_id")
		return [f"USt-IdNr. {vat_id} (Tax ID)", f"Steuernummer {steuernummer}"] if vat_id else []

	def check_wizard_company(self, company: str, params: dict, home_region: str | None, unregistered: bool):
		import frappe

		from erpnext_demo_gen.service import DemoDataError

		if frappe.db.get_value("Company", company, "chart_of_accounts") != CHART:
			raise DemoDataError(
				f"{company!r} does not use the {CHART} chart; the German demo needs it for its VAT "
				"templates. Install without --use-wizard-company to get a new demo company."
			)
		super().check_wizard_company(company, params, home_region, unregistered)

	def validate_pack(self, pack: dict, check):
		state = (pack.get("company") or {}).get("home_state")
		check(state in CITIES, "company.home_state", f"must be a Bundesland: {', '.join(CITIES)}")
		vat = pack.get("vat") or {}
		check(vat.get("standard") == 19 and vat.get("reduced") == 7, "vat", "German VAT is standard 19, reduced 7")
		families = (pack.get("catalog") or {}).get("families") or []
		for i, f in enumerate(families):
			check(f.get("vat", "standard") in VAT_CLASSES, f"catalog.families[{i}].vat", f"must be one of {', '.join(VAT_CLASSES)}")
		for i, s in enumerate((pack.get("supplies") or {}).get("items") or []):
			check(s.get("vat", "standard") in VAT_CLASSES, f"supplies.items[{i}].vat", f"must be one of {', '.join(VAT_CLASSES)}")
		mix = (pack.get("behavior") or {}).get("vat_registration") or {}
		check(mix and set(mix) <= {"registered", "unregistered"} and abs(sum(mix.values()) - 1) < 1e-6,
			"behavior.vat_registration", "needs registered and unregistered shares adding up to 1")
		banking = pack.get("banking") or {}
		for role in ("main", "collection"):
			bank = banking.get(role) or {}
			blz = str(bank.get("blz") or "")
			check(len(blz) == 8 and blz.isdigit(), f"banking.{role}.blz", "must be the bank's 8-digit Bankleitzahl")
			bic = str(bank.get("bic") or "")
			check(len(bic) in (8, 11) and bic.isalnum(), f"banking.{role}.bic", "must be an 8 or 11 character BIC")

	# ---------------------------------------------------------- verify
	def tax_checks(self, ctx) -> list:
		"""Germany: every invoice's VAT matches its items' rates (19% or 7%); the VAT
		accounts agree with the invoices (output VAT, input VAT: the UStVA totals).
		Kleinunternehmer: no VAT on sales and the § 19 note; non-deductible VAT on bills."""
		import frappe
		from frappe.utils import flt

		from erpnext_demo_gen.verify import TOLERANCE, Check

		templates = frappe.get_all(
			"Item Tax Template Detail",
			filters={"parent": ["in", frappe.get_all("Item Tax Template", filters={"company": ctx.company}, pluck="name")]},
			fields=["parent", "tax_rate"],
		)
		rate_of = {}
		for t in templates:  # the template's rate is its highest row (19 % or 7 %)
			rate_of[t.parent] = max(rate_of.get(t.parent, 0), flt(t.tax_rate))

		def rate_mismatches(doctype):
			rows = frappe.db.sql(
				f"""select p.name, p.base_total_taxes_and_charges tax, i.base_net_amount net, ifnull(i.item_tax_template, '') tpl
				from `tab{doctype}` p join `tab{doctype} Item` i on i.parent = p.name
				where p.company = %s and p.docstatus = 1""",
				ctx.company,
				as_dict=True,
			)
			expected, actual, lines = {}, {}, {}
			for r in rows:
				expected[r.name] = expected.get(r.name, 0) + flt(r.net) * rate_of.get(r.tpl, 0) / 100
				actual[r.name] = flt(r.tax)
				lines[r.name] = lines.get(r.name, 0) + 1
			wrong = [n for n in expected if abs(expected[n] - actual[n]) > 0.02 * lines[n] + 0.02]
			untaxed = [n for n in expected if not actual[n]]
			return len(expected), wrong, untaxed, sum(actual.values())

		if ctx.run.params.get("registration") == "unregistered":  # Kleinunternehmer; no UStVA
			count, wrong, _, _ = rate_mismatches("Purchase Invoice")  # unregistered suppliers: rate 0
			no_note = frappe.db.sql_list(
				"""select name from `tabSales Invoice` where company=%s and docstatus=1
				and ifnull(terms, '') not like %s""",
				(ctx.company, "%§ 19 UStG%"),
			)
			return [
				*self.unregistered_checks(ctx, "VAT"),
				Check("bills carry non-deductible VAT at their items' rates (19% / 7%)", bool(count) and not wrong,
					f"{count} bills" + (f"; VAT differs from the item rates: {wrong[:5]}" if wrong else "")),
				Check("sales invoices carry the § 19 UStG note", not no_note, ", ".join(no_note[:5]) or "all"),
			]

		checks = []
		totals = {}
		for doctype, label in (("Sales Invoice", "sales invoices"), ("Purchase Invoice", "bills")):
			count, wrong, untaxed, total = rate_mismatches(doctype)
			totals[doctype] = total
			checks.append(
				Check(
					f"{label} carry VAT at their items' rates (19% / 7%)",
					bool(count) and not wrong and not untaxed,
					f"{count} {label}"
					+ (f"; VAT differs from the item rates: {wrong[:5]}" if wrong else "")
					+ (f"; without VAT: {untaxed[:5]}" if untaxed else ""),
				)
			)

		reduced_templates = [n for n, r in rate_of.items() if r == 7] or [""]
		reduced_items = frappe.db.sql(
			"""select count(distinct t.parent) from `tabItem Tax` t where t.item_tax_template in %s""", (reduced_templates,)
		)[0][0]
		if reduced_items:  # the pack has 7% items (staff coffee): their bills use the 7% account
			reduced = frappe.db.sql(
				"""select count(*) from `tabPurchase Invoice Item` i join `tabPurchase Invoice` p on p.name = i.parent
				where p.company = %s and p.docstatus = 1 and i.item_tax_template in %s""",
				(ctx.company, reduced_templates),
			)[0][0]
			checks.append(Check("reduced-rate (7%) items are billed at 7%", bool(reduced), f"{reduced} bill lines at 7%"))

		def balance(kind):  # credit - debit on the VAT accounts the templates use
			doctype = "Sales Taxes and Charges" if kind == "output" else "Purchase Taxes and Charges"
			accounts = sorted(set(frappe.get_all(doctype, filters={"parenttype": f"{doctype} Template", "parent": ["in", frappe.get_all(f"{doctype} Template", filters={"company": ctx.company}, pluck="name")]}, pluck="account_head")))
			if not accounts:
				return 0.0
			value = frappe.db.sql(
				"""select sum(credit - debit) from `tabGL Entry` where company = %s and is_cancelled = 0 and account in %s""",
				(ctx.company, accounts),
			)[0][0]
			return flt(value)

		output_vat, input_vat = balance("output"), -balance("input")
		ok = abs(output_vat - totals["Sales Invoice"]) <= TOLERANCE * 10 and abs(input_vat - totals["Purchase Invoice"]) <= TOLERANCE * 10
		checks.append(
			Check(
				"VAT accounts match the invoices (UStVA: output VAT, input VAT)",
				ok,
				f"output {output_vat:,.2f} vs invoices {totals['Sales Invoice']:,.2f}; "
				f"input {input_vat:,.2f} vs bills {totals['Purchase Invoice']:,.2f}; "
				f"payable {output_vat - input_vat:,.2f}",
			)
		)
		return checks
