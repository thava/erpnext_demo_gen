import datetime as dt
import random

from frappe.tests import UnitTestCase

from demo_data.locales import get_locale
from demo_data.locales.us import routing_number
from demo_data.packs import load_pack
from demo_data.planner import PlanContext, make_plan
from demo_data.setup.company import date_range


class TestUSLocale(UnitTestCase):
	def test_routing_numbers_have_a_valid_check_digit(self):
		rng = random.Random(1)
		for _ in range(50):
			n = routing_number(rng, "1140")
			self.assertEqual(len(n), 9)
			self.assertTrue(n.startswith("1140"))
			total = sum(int(d) * w for d, w in zip(n, (3, 7, 1, 3, 7, 1, 3, 7, 1), strict=True))
			self.assertEqual(total % 10, 0, n)

	def test_regions_and_fiscal_year(self):
		us = get_locale("US")
		self.assertEqual(us.resolve_region("tx"), "Texas")
		self.assertEqual(us.resolve_region("Texas "), "Texas")
		self.assertIsNone(us.resolve_region("Tamil Nadu"))
		self.assertEqual(us.fiscal_year_starts(dt.date(2025, 11, 9), dt.date(2026, 11, 8)), [dt.date(2025, 1, 1), dt.date(2026, 1, 1)])
		self.assertEqual(us.fiscal_year_end(dt.date(2026, 1, 1)), dt.date(2026, 12, 31))

	def test_plan_is_texan(self):
		pack = load_pack("furniture_store_us")
		docs = make_plan(PlanContext(pack, "small", 3, "Texas", *date_range(dt.date(2026, 11, 8), 12), True))
		customers = [d.params for d in docs if d.doctype == "Customer"]
		self.assertTrue(all(c["address"]["state"] == "Texas" for c in customers))  # sells only in Texas
		resellers = [c for c in customers if c.get("tax_category") == "Reseller"]
		self.assertTrue(resellers and all(c["resale_certificate"] and c["tax_id"] for c in resellers))
		suppliers = [d.params for d in docs if d.doctype == "Supplier"]
		self.assertTrue(any(s["address"]["state"] != "Texas" for s in suppliers))  # some out of state (use tax)
		items = {d.key: d.params for d in docs if d.doctype == "Item"}
		self.assertTrue(all(p["tax_class"] == "resale" for k, p in items.items() if p["family"] != "supplies"))
		self.assertIn("food", {p["tax_class"] for p in items.values() if p["family"] == "supplies"})
		modes = {d.params.get("mode") for d in docs if d.doctype == "Payment Entry"} - {None}
		self.assertTrue({"ACH", "Check", "Cash"} <= modes and not any("UPI" in m for m in modes))
