import random

from frappe.tests import UnitTestCase

from demo_data.india import geo
from demo_data.india.gstin import make_gstin, make_pan


class TestGstin(UnitTestCase):
	def test_generated_gstins_pass_india_compliance_validation(self):
		from india_compliance.gst_india.utils import guess_gst_category, is_valid_pan, validate_gstin

		rng = random.Random("test")
		states = sorted(geo.CITIES)
		for i in range(300):
			holder = ("company", "person", "firm", "huf")[i % 4]
			pan = make_pan(rng, holder, "Sample")
			self.assertTrue(is_valid_pan(pan), pan)
			gstin = make_gstin(geo.state_code(states[i % len(states)]), pan, 1 + i % 9)
			self.assertEqual(validate_gstin(gstin), gstin)  # throws on a bad check digit
			self.assertEqual(guess_gst_category(gstin, "India"), "Registered Regular")

	def test_gstin_state_code_and_pan(self):
		pan = make_pan(random.Random(1), "company", "Cedar")
		gstin = make_gstin("33", pan)
		self.assertTrue(gstin.startswith("33" + pan))
		self.assertEqual(pan[3:5], "CC")  # holder type C, name initial C

	def test_deterministic(self):
		self.assertEqual(make_pan(random.Random(7)), make_pan(random.Random(7)))


class TestGeo(UnitTestCase):
	def test_cities_match_india_compliance_states_and_pincode_ranges(self):
		from india_compliance.gst_india.constants import STATE_NUMBERS, STATE_PINCODE_MAPPING

		for state, cities in geo.CITIES.items():
			self.assertIn(state, STATE_NUMBERS)
			ranges = STATE_PINCODE_MAPPING[state]
			if isinstance(ranges[0], int):
				ranges = (ranges,)
			for city, prefix in cities:
				self.assertTrue(any(lo <= prefix <= hi for lo, hi in ranges), f"{city}, {state}: {prefix}")

	def test_make_address_passes_pincode_validation(self):
		import frappe
		from india_compliance.gst_india.utils import validate_pincode

		rng = random.Random(3)
		for state in geo.CITIES:
			address = frappe._dict(geo.make_address(rng, state))
			validate_pincode(address)  # throws when outside the state's range

	def test_resolve_state_accepts_names_and_codes(self):
		from india_compliance.gst_india.constants import INDIAN_STATES

		self.assertEqual(set(geo.STATE_ABBREVIATIONS), set(INDIAN_STATES) - {"Other Territory"})
		self.assertEqual(len(set(geo.STATE_ABBREVIATIONS.values())), len(geo.STATE_ABBREVIATIONS))
		for value in ("Tamil Nadu", "tamil nadu", "Tamilnadu", "TAMIL-NADU", " TN ", "tn", "33"):
			self.assertEqual(geo.resolve_state(value), "Tamil Nadu")
		self.assertEqual(geo.resolve_state("TS"), "Telangana")
		self.assertEqual(geo.resolve_state("Jammu & Kashmir"), "Jammu and Kashmir")
		self.assertEqual(geo.resolve_state("7"), "Delhi")
		self.assertIsNone(geo.resolve_state("XX"))
