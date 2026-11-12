import copy

from frappe.tests import UnitTestCase

from erpnext_demo_gen.packs import PackError, list_packs, load_pack, merge, validate_pack


class TestPacks(UnitTestCase):
	def test_every_pack_is_valid(self):
		ids = [p["id"] for p in list_packs()]
		self.assertIn("furniture_store", ids)
		self.assertNotIn("india_trading", ids)  # abstract
		for pack_id in ids:
			load_pack(pack_id)

	def test_inheritance(self):
		pack = load_pack("furniture_store")
		self.assertEqual(pack["company"]["home_state"], "Tamil Nadu")  # from base
		self.assertEqual(pack["company"]["warehouses"], ["Showroom", "Godown"])  # list replaced
		self.assertEqual(pack["sizes"]["medium"]["months"], 12)  # from base
		self.assertEqual(pack["behavior"]["seasonality"]["monthly_index"][8], 1.4)  # overridden
		self.assertIn("payment_outcomes", pack["behavior"])  # sibling key kept

	def test_append_marker(self):
		merged = merge({"a": [1], "b": {"c": [2]}}, {"a+": [3], "b": {"c+": [4]}})
		self.assertEqual(merged, {"a": [1, 3], "b": {"c": [2, 4]}})

	def test_errors_are_collected_with_paths(self):
		pack = copy.deepcopy(load_pack("furniture_store"))
		pack["catalog"]["families"][0]["hsn"] = "9401"
		pack["catalog"]["families"][1]["gst_rate"] = 40
		pack["channels"][0]["share"] = 0.5
		pack["company"]["home_state"] = "Atlantis"
		errors = "\n".join(validate_pack(pack))
		self.assertIn("catalog.families[0].hsn", errors)
		self.assertIn("catalog.families[1].gst_rate", errors)
		self.assertIn("channels: shares must add up to 1", errors)
		self.assertIn("company.home_state", errors)

	def test_unknown_hsn_rejected(self):
		pack = copy.deepcopy(load_pack("furniture_store"))
		pack["catalog"]["families"][0]["hsn"] = "94035000"  # right length, not in the HSN list
		self.assertTrue(any("HSN list" in e for e in validate_pack(pack)))

	def test_missing_pack(self):
		with self.assertRaises(PackError):
			load_pack("no_such_pack")
