"""Wizard mode never uses a real tax ID, and --unregistered per country (design 5.20, DEC-35)."""

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from erpnext_demo_gen.locales import get_locale
from erpnext_demo_gen.service import DemoDataError

COMPANY = "My Own Company"


def company_fields(tax_id=None, gstin=None, chart=None):
	"""A stand-in for frappe.db.get_value("Company", COMPANY, field)."""
	values = {"tax_id": tax_id, "gstin": gstin, "chart_of_accounts": chart}

	def get_value(doctype, name, field, *args, **kwargs):
		assert (doctype, name) == ("Company", COMPANY), (doctype, name)
		return values[field]

	return get_value


def check(code, tax_id=None, gstin=None, address=None, unregistered=False, home=None, ours=()):
	"""Run the locale's wizard-company check against a company with the given tax IDs."""
	locale = get_locale(code)
	chart = getattr(__import__(type(locale).__module__, fromlist=["CHART"]), "CHART", None)
	params = {"home_state": "Default State", "fictitious_gstin": False}
	with (
		patch.object(frappe.db, "get_value", company_fields(tax_id, gstin, chart)),
		patch.object(frappe, "get_all", fake_get_all(address, ours)),
	):
		locale.check_wizard_company(COMPANY, params, home, unregistered)
	return params


def fake_get_all(address, ours):
	"""Company addresses with a GSTIN, and the Demo Data Records naming DemoGen's own."""

	def get_all(doctype, *args, **kwargs):
		if doctype == "Address":
			return [frappe._dict(name=address, gstin="33AAAAA0000A1Z5")] if address else []
		if doctype == "Demo Data Record":
			return [a for a in ours]
		return []

	return get_all


class TestWizardCompanyTaxId(UnitTestCase):
	def test_a_company_tax_id_is_refused_in_every_country(self):
		for code in ("IN", "US", "AE", "DE"):
			with self.assertRaisesRegex(DemoDataError, "has a tax ID .*never uses a real one", msg=code):
				check(code, tax_id="SOME-REAL-ID")

	def test_india_refuses_a_gstin_on_the_company_or_its_address(self):
		with self.assertRaisesRegex(DemoDataError, "Company GSTIN"):
			check("IN", gstin="27AAPFU0939F1ZV")
		with self.assertRaisesRegex(DemoDataError, "GSTIN on address ADDR-1"):
			check("IN", address="ADDR-1")
		with self.assertRaisesRegex(DemoDataError, "has a tax ID"):  # also when unregistered
			check("IN", address="ADDR-1", unregistered=True)

	def test_india_ignores_the_made_up_address_of_a_run_being_resumed(self):
		self.assertTrue(check("IN", address="ADDR-DEMO", ours=("ADDR-DEMO",))["fictitious_gstin"])

	def test_india_without_gstin_gets_a_made_up_one_unless_unregistered(self):
		self.assertTrue(check("IN")["fictitious_gstin"])
		self.assertFalse(check("IN", unregistered=True)["fictitious_gstin"])
		self.assertEqual(check("IN", home="Karnataka")["home_state"], "Karnataka")

	def test_other_countries_without_tax_id_proceed(self):
		for code in ("US", "AE", "DE"):
			params = check(code)
			self.assertEqual(params["home_state"], "Default State", code)
			self.assertFalse(params["fictitious_gstin"], code)


class TestUnregisteredOption(UnitTestCase):
	def test_india_uae_and_germany_accept_it(self):
		for code in ("IN", "AE", "DE"):
			get_locale(code).check_options(True)

	def test_us_refuses_it_with_the_reason(self):
		with self.assertRaisesRegex(DemoDataError, "sales tax permit"):
			get_locale("US").check_options(True)

	def test_every_supporting_locale_warns_about_the_threshold(self):
		for code in ("IN", "AE", "DE"):
			self.assertIn("threshold" if code != "DE" else "limits", get_locale(code).unregistered_warning, code)

	def test_registered_is_accepted_everywhere(self):
		for code in ("IN", "US", "AE", "DE"):
			get_locale(code).check_options(False)

	def test_cli_options(self):
		from erpnext_demo_gen.commands import install

		names = {o for p in install.params for o in p.opts}
		self.assertIn("--unregistered", names)
		self.assertFalse(names & {"--no-gst", "--fictitious-gstin"})
