import random

from frappe.tests import UnitTestCase

from demo_data import naming
from demo_data.setup.company import date_range, fiscal_year_starts


class TestNaming(UnitTestCase):
	def test_company_name_shape_and_determinism(self):
		a = naming.company_name(random.Random("1:company-name"), ["Furniture"], "Pvt Ltd")
		b = naming.company_name(random.Random("1:company-name"), ["Furniture"], "Pvt Ltd")
		self.assertEqual(a, b)
		self.assertRegex(a, r"^\w+ \w+ Furniture Pvt Ltd$")
		self.assertFalse(any(ch.isdigit() for ch in a))  # no visible counters (DEC-10)

	def test_abbreviation_skips_suffix_and_avoids_collisions(self):
		self.assertEqual(naming.abbreviation("Cedar Ridge Furniture Pvt Ltd", set()), "CRF")
		self.assertEqual(naming.abbreviation("Cedar Ridge Furniture Pvt Ltd", {"crf"}), "CRF2")


class TestDates(UnitTestCase):
	def test_twelve_months_span_two_fiscal_years(self):
		import datetime as dt

		start, end = date_range(dt.date(2026, 11, 8), 12)
		self.assertEqual((start, end), (dt.date(2025, 11, 9), dt.date(2026, 11, 8)))
		self.assertEqual(fiscal_year_starts(start, end), [dt.date(2025, 4, 1), dt.date(2026, 4, 1)])

	def test_range_inside_one_fiscal_year(self):
		import datetime as dt

		self.assertEqual(fiscal_year_starts(dt.date(2026, 4, 1), dt.date(2027, 3, 31)), [dt.date(2026, 4, 1)])
