"""Locales: everything that depends on the company's country (design 5.11, locale layer).

A pack names its locale (`locale: IN`, set once in its base pack, e.g. india_trading).
The planner, setup, writers and checks ask the locale for country-specific data and
behaviour instead of assuming India.

Planning methods take the random stream they should draw from and must draw in a
fixed order, so a plan stays reproducible from its seed (golden plans).
"""

import random

DEFAULT_LOCALE = "IN"


class Locale:
	"""What a country provides. India is the first implementation (locales/india.py)."""

	code = ""  # ISO 3166-1 alpha-2
	country = ""  # ERPNext Country name
	aliases: tuple[str, ...] = ()  # other names accepted by --country (compared squashed)

	# ---------------------------------------------------------- planning (pure)
	season_start_month = 1  # month of the pack's seasonality index 0 (the fiscal year start)

	def regions(self) -> list[str]:
		"""States or provinces the demo places parties in, sorted."""
		raise NotImplementedError

	def person(self, rng: random.Random, region: str) -> tuple[str, str]:
		"""(first name, last name) typical for the region."""
		raise NotImplementedError

	def business_name(self, rng: random.Random, nouns: list[str]) -> str:
		"""A made-up business name with a legal suffix usual in the country."""
		raise NotImplementedError

	def phone(self, rng: random.Random) -> str:
		raise NotImplementedError

	def company_name(self, rng: random.Random, nouns: list[str]) -> str:
		"""The demo company's own name (with company_suffix)."""
		raise NotImplementedError

	def address(self, rng: random.Random, region: str) -> dict:
		"""Address fields for a random place in the region."""
		raise NotImplementedError

	def business_tax(self, rng: random.Random, name: str, region: str, registered: bool, category: str) -> dict:
		"""Tax identity fields of a business party (planner params)."""
		raise NotImplementedError

	def individual_tax(self) -> dict:
		"""Tax identity fields of a private person (planner params)."""
		raise NotImplementedError

	def customer_category(self, rng: random.Random, behavior: dict, sales_tax: bool) -> tuple[bool, str]:
		"""(registered, category) of a business customer, drawn from the pack's mix."""
		raise NotImplementedError

	def customer_home_share(self, behavior: dict, sales_tax: bool) -> float:
		"""Share of business customers in the home region."""
		raise NotImplementedError

	def item_tax(self, family: dict, pack: dict) -> dict:
		"""Tax fields of an item (planner params), from its pack family."""
		raise NotImplementedError

	def item_tax_rate(self, item_params: dict) -> float:
		"""The sales tax rate (percent) an item's price carries."""
		raise NotImplementedError

	def purchase_tax_rate(self, item_params: dict) -> float:
		"""The tax rate (percent) the supplier charges when the shop buys the item for resale."""
		return self.item_tax_rate(item_params)

	prices_include_tax = False  # True when shelf prices already include the sales tax

	# payments: mode names come from the pack's banking section
	payment_modes: tuple[str, ...] = ("Cash", "Wire Transfer", "Cheque", "Card")  # allowed in a pack
	counter_modes: tuple[str, ...] = ()  # modes the shop counter collects into the collection account

	def mode_limit(self, mode: str, banking: dict) -> float | None:
		"""Largest amount a mode may carry in one payment, or None."""
		return None

	def over_limit_mode(self, mode: str) -> str:
		"""The mode used instead when a payment is over its mode's limit."""
		raise NotImplementedError

	def payment_reference(self, rng: random.Random, mode: str, amount: float, when, bank: dict, banking: dict) -> str:
		"""The bank's reference for a payment (cheque number, transfer reference, ...)."""
		raise NotImplementedError

	def sweep_reference(self, rng: random.Random, source: str, when, banking: dict) -> str:
		"""Reference of the weekly move from the collection account or cash box to the main account."""
		raise NotImplementedError

	# ---------------------------------------------------------- setup (writes to the site)
	currency = ""
	company_suffix = ""  # legal form appended to generated company names
	timezone = ""  # for the setup wizard of a snapshot build site
	wizard_chart = "Standard"  # chart of accounts of a snapshot build site's wizard company
	# ledgers of the opening funding entry, by account_name (the chart's own names)
	funding_accounts = {"share_capital": "Capital Stock", "term_loan": "Secured Loans"}

	def company_fields(self, params) -> dict:
		"""Fields of the new demo Company beyond its name and abbreviation."""
		raise NotImplementedError

	def company_address(self, rng: random.Random, company: str, region: str, wizard: bool) -> dict | None:
		"""The company's own Address fields (with its tax ID), or None when it has none."""
		raise NotImplementedError

	def wants_company_address(self, params) -> bool:
		raise NotImplementedError

	def fiscal_year_starts(self, start, end) -> list:
		"""Start dates of every fiscal year the date range touches."""
		raise NotImplementedError

	def fiscal_year_end(self, fy_start):
		raise NotImplementedError

	def registration_lines(self, run, company: str) -> list[str]:
		"""The demo company's (made-up) registrations, one per line, for its Registration
		Details; tax IDs without a field of their own go here too."""
		import frappe

		tax_id = frappe.db.get_value("Company", company, "tax_id")
		return [f"Tax ID {tax_id}"] if tax_id else []

	def setup_taxes(self, run, company: str, abbr: str, pack: dict):
		"""Tax set-up beyond what ERPNext and the country's app create with the company."""

	def bank_account_fields(self, rng: random.Random, bank: dict) -> dict:
		"""Made-up account number and branch code of a demo Bank Account."""
		raise NotImplementedError

	# ---------------------------------------------------------- writing documents
	def writer_context(self, run, company: str) -> dict:
		"""Site facts for WriteContext: territory, tax_templates (key -> Item Tax
		Template) and locale_data (anything else the locale's builders need)."""
		raise NotImplementedError

	def party_fields(self, p, w) -> dict:
		"""Customer or Supplier fields from the planned party (tax identity, address)."""
		raise NotImplementedError

	def item_fields(self, p, w) -> dict:
		"""Item fields for tax (classification code, Item Tax Template rows)."""
		raise NotImplementedError

	def item_defaults(self, p, w) -> dict:
		"""Extra Item Default fields for the demo company (e.g. an income account)."""
		return {}

	def purchase_taxes(self, doc, w):
		"""Choose the tax template of a purchase order when ERPNext would not."""

	def sales_taxes(self, doc, w):
		"""Choose the tax template of a quotation, sales order or counter sale when needed."""

	def finish_purchase_invoice(self, doc, w) -> bool:
		"""Adjust a saved purchase invoice before submit (e.g. UAE recoverable VAT); True to save again."""
		return False

	# ---------------------------------------------------------- install parameters
	required_apps: tuple[str, ...] = ("erpnext",)
	unregistered_warning = ""  # shown (and needing --force) when installing unregistered
	# True when only suppliers with a tax ID charge tax (UAE: the TRN is the registration);
	# False when suppliers without one charge it too (Germany: USt-IdNr. only for EU trade)
	tax_id_means_registered = True

	def preflight_problems(self) -> list[str]:
		"""Site settings that make installing risky (overridable with --force)."""
		return []

	def resolve_region(self, text: str) -> str | None:
		"""A region name from a name, code or number as the user typed it."""
		raise NotImplementedError

	def region_choices(self) -> str:
		"""The supported home regions, for error messages."""
		raise NotImplementedError

	def home_regions(self) -> list[str]:
		"""Regions a demo company can be based in."""
		return self.regions()

	def check_options(self, unregistered: bool):
		"""Refuse install options that do not apply to the country (DEC-35, DEC-36)."""
		from erpnext_demo_gen.service import DemoDataError

		if unregistered:
			raise DemoDataError(f"--unregistered is not supported yet for {self.country}")

	def validate_pack(self, pack: dict, check):
		"""Country-specific pack checks; check(ok, path, message) records an error."""

	def tax_checks(self, ctx) -> list:
		"""verify's tax checks for a run in this country (a list of verify.Check)."""
		return []

	def unregistered_checks(self, ctx, tax: str) -> list:
		"""verify for --unregistered (DEC-36, DEC-37): sales carry no tax; purchases from
		registered suppliers carry tax only on the not-recoverable account, those from
		unregistered suppliers none (tax_id_means_registered). In wizard mode only the run's
		documents count."""
		import frappe

		from erpnext_demo_gen.verify import Check

		account = (ctx.run.params.get("not_recoverable") or {}).get("account")

		def ours(names):
			if not names or not ctx.run.params.get("use_wizard_company"):
				return names
			mine = set(frappe.get_all("Demo Data Record", filters={"run": ctx.run.name, "ref_name": ["in", names]}, pluck="ref_name"))
			return [n for n in names if n in mine]

		taxed_sales = []
		for doctype in ("Quotation", "Sales Order", "Sales Invoice"):
			taxed_sales += frappe.db.sql_list(
				f"""select d.name from `tab{doctype}` d where d.company=%s and d.docstatus=1
				and (d.total_taxes_and_charges != 0 or exists (select 1 from `tabSales Taxes and Charges` t where t.parent=d.name))""",
				ctx.company,
			)
		charges = "ifnull(s.tax_id, '') != ''" if self.tax_id_means_registered else "1=1"
		wrong_bills = []
		for doctype in ("Purchase Order", "Purchase Invoice"):
			wrong_bills += frappe.db.sql_list(
				f"""select d.name from `tab{doctype}` d join tabSupplier s on s.name=d.supplier
				where d.company=%(company)s and d.docstatus=1 and (
					({charges} and (
						not exists (select 1 from `tabPurchase Taxes and Charges` t where t.parent=d.name and t.account_head=%(account)s)
						or exists (select 1 from `tabPurchase Taxes and Charges` t where t.parent=d.name and t.account_head!=%(account)s)))
					or (not ({charges}) and d.total_taxes_and_charges != 0))""",
				{"company": ctx.company, "account": account},
			)
		taxed_sales, wrong_bills = ours(taxed_sales), ours(wrong_bills)
		return [
			Check(f"sales carry no {tax} (unregistered)", not taxed_sales, ", ".join(taxed_sales[:5]) or "none"),
			Check(
				f"purchase {tax} goes to {account or 'the not-recoverable account'} (unregistered)",
				bool(account) and not wrong_bills,
				", ".join(wrong_bills[:5]) or "all as expected",
			),
		]

	def company_tax_id(self, company: str) -> str | None:
		"""Where the company's own tax ID is recorded (a description), or None without one."""
		import frappe

		return "Company Tax ID" if frappe.db.get_value("Company", company, "tax_id") else None

	def check_wizard_company(self, company: str, params: dict, home_region: str | None, unregistered: bool):
		"""Validate installing into the user's own company and settle params (home
		region); raise DemoDataError when it cannot work. A company with a tax ID is
		refused in every country: the demo never issues invoices under a real one (DEC-35)."""
		from erpnext_demo_gen.service import DemoDataError

		where = self.company_tax_id(company)
		if where:
			raise DemoDataError(
				f"{company} has a tax ID ({where}); DemoGen never uses a real one. "
				"Install without --use-wizard-company to get a new demo company."
			)
		params["home_state"] = home_region or params["home_state"]


_LOCALES: dict[str, Locale] = {}


def get_locale(code_or_pack: str | dict | None = None) -> Locale:
	"""The locale for a code ("IN") or a pack (its `locale` key; India when absent)."""
	code = code_or_pack.get("locale") if isinstance(code_or_pack, dict) else code_or_pack
	code = (code or DEFAULT_LOCALE).upper()
	if code not in _LOCALES:
		if code == "IN":
			from erpnext_demo_gen.locales.india import IndiaLocale

			_LOCALES[code] = IndiaLocale()
		elif code == "US":
			from erpnext_demo_gen.locales.us import USLocale

			_LOCALES[code] = USLocale()
		elif code == "AE":
			from erpnext_demo_gen.locales.ae import AELocale

			_LOCALES[code] = AELocale()
		elif code == "DE":
			from erpnext_demo_gen.locales.de import DELocale

			_LOCALES[code] = DELocale()
		else:
			raise KeyError(f"unknown locale {code!r}; known: {', '.join(known_locales())}")
	return _LOCALES[code]


def known_locales() -> tuple[str, ...]:
	return ("IN", "US", "AE", "DE")


def squash(text: str) -> str:
	"""Lower case, letters and digits only: "United States", "united-states" and
	"UnitedStates" all become "unitedstates"."""
	return "".join(ch for ch in text.lower() if ch.isalnum())


def country_choices() -> str:
	return ", ".join(f"{code} ({get_locale(code).country})" for code in known_locales())


def resolve_country(text: str | None) -> str | None:
	"""The locale code for a country code or name, ignoring case, spaces and punctuation
	(IN, india, US, usa, "United States", united-states); None when unknown."""
	if not text:
		return None
	wanted = squash(text)
	for code in known_locales():
		locale = get_locale(code)
		if wanted in {squash(code), squash(locale.country), *(squash(a) for a in locale.aliases)}:
			return code
	return None
