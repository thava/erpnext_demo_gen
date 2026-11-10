from frappe.tests import UnitTestCase

from demo_data.locales import resolve_country
from demo_data.packs import PackNotFound, default_packs, describe, find_pack, list_packs


class TestCountry(UnitTestCase):
	def test_country_names_are_forgiving(self):
		for text in ("IN", "in", "India", " INDIA ", "Bharat"):
			self.assertEqual(resolve_country(text), "IN", text)
		for text in ("US", "usa", "U.S.A.", "United States", "united-states", "unitedstates", "United States of America"):
			self.assertEqual(resolve_country(text), "US", text)
		for text in ("UAE", "uae", "United Arab Emirates", "united-arab-emirates", "AE", "Emirates"):
			self.assertEqual(resolve_country(text), "AE", text)
		for text in ("DE", "de", "Germany", "deutschland", "GER"):
			self.assertEqual(resolve_country(text), "DE", text)
		for text in ("", None, "UK", "Indiana"):
			self.assertIsNone(resolve_country(text), text)

	def test_packs_by_country(self):
		self.assertEqual(default_packs(), {"IN": "furniture_store", "US": "furniture_store", "AE": "furniture_store", "DE": "furniture_store"})
		self.assertEqual(find_pack("Germany"), "furniture_store_de")
		self.assertEqual(find_pack("UAE"), "furniture_store_ae")
		self.assertEqual(find_pack("US"), "furniture_store_us")  # the US default
		self.assertEqual(find_pack("india"), "furniture_store")
		self.assertEqual(find_pack("IN", "electrical_distributor"), "electrical_distributor")
		self.assertEqual(find_pack("United States", "furniture_store"), "furniture_store_us")
		with self.assertRaisesRegex(PackNotFound, "exists for IN"):
			find_pack("US", "electrical_distributor")
		with self.assertRaisesRegex(PackNotFound, "Unknown country"):
			find_pack("UK")
		with self.assertRaises(PackNotFound):
			find_pack("US", "furniture_store_us")  # file ids are not pack names
		self.assertEqual(describe("furniture_store_us"), "furniture_store (US)")

	def test_every_pack_names_its_country(self):
		for p in list_packs():
			self.assertIn(p["country"], ("IN", "US", "AE", "DE"), p["id"])
			self.assertTrue(p["sizes"], p["id"])

	def test_uae_iban_check_digits(self):
		import random

		from demo_data.locales.ae import iban

		rng = random.Random(5)
		for _ in range(30):
			n = iban(rng, "260")
			self.assertEqual((len(n), n[:2], n[4:7]), (23, "AE", "260"))
			self.assertEqual(int("".join(str(int(c, 36)) for c in n[4:] + n[:4])) % 97, 1, n)

	def test_german_iban_and_vat_id_check_digits(self):
		import random

		from demo_data.locales.de import iban, vat_id

		rng = random.Random(6)
		for _ in range(30):
			n = iban(rng, "70150000")
			self.assertEqual((len(n), n[:2], n[4:12]), (22, "DE", "70150000"))
			self.assertEqual(int("".join(str(int(c, 36)) for c in n[4:] + n[:4])) % 97, 1, n)
		for known in ("DE136695976", "DE811569869"):  # real VAT IDs, to test the algorithm
			self.assertEqual(vat_id_check(known[2:10]), int(known[10]), known)
		for _ in range(30):
			v = vat_id(rng)
			self.assertEqual((len(v), v[:2], vat_id_check(v[2:10])), (11, "DE", int(v[10])), v)


def vat_id_check(digits: str) -> int:
	"""ISO 7064 MOD 11,10, the German VAT ID check digit, written independently of de.py."""
	product = 10
	for d in digits:
		s = (int(d) + product) % 10
		if s == 0:
			s = 10
		product = (2 * s) % 11
	check = 11 - product
	return 0 if check == 10 else check


class TestLocales(UnitTestCase):
	def test_every_locale_brings_its_own_tax_checks(self):
		"""A locale that forgets tax_checks would silently skip verify's tax checks."""
		from demo_data.locales import Locale, get_locale, known_locales

		for code in known_locales():
			self.assertIsNot(type(get_locale(code)).tax_checks, Locale.tax_checks, code)
