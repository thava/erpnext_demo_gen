import datetime as dt

from frappe.tests import UnitTestCase

from erpnext_demo_gen import snapshot


class TestVersionPolicy(UnitTestCase):
	def test_parse_version(self):
		self.assertEqual(snapshot.parse_version("16.54.0"), (16, 54, 0))
		self.assertEqual(snapshot.parse_version("1.0.0-beta.4"), (1, 0, 0))
		self.assertEqual(snapshot.parse_version("3"), (3, 0, 0))

	def test_actions(self):
		act = lambda s, b: snapshot.version_action("erpnext", s, b)[0]  # noqa: E731
		self.assertEqual(act("16.53.0", "16.53.0"), "same")
		self.assertEqual(act("16.50.0", "16.53.0"), "migrate")  # older, same major
		self.assertEqual(act("16.53.0", "16.53.2"), "migrate")  # older patch
		self.assertEqual(act("16.53.1", "16.53.0"), "refuse")  # newer patch: a downgrade
		self.assertEqual(act("16.60.0", "16.53.0"), "refuse")  # newer minor
		self.assertEqual(act("15.40.0", "16.53.0"), "refuse")  # older major
		self.assertEqual(act("17.0.0", "16.53.0"), "refuse")  # newer major

	def test_development_versions_compare_commits(self):
		def act(snap, ours, s="17.0.0-dev", b="17.0.0-dev"):
			return snapshot.version_action("erpnext", s, b, snap, ours)[0]

		old = {"commit": "aaa1111", "date": "2026-11-01T10:00:00+00:00"}
		new = {"commit": "bbb2222", "date": "2026-11-10T10:00:00+00:00"}
		self.assertEqual(act(old, {"commit": "aaa1111-dirty", "date": old["date"]}), "same")
		self.assertEqual(act(old, new), "migrate")  # snapshot from an older develop commit
		self.assertEqual(act(new, old), "refuse")  # newer: update the bench first
		self.assertEqual(act({"commit": "ccc"}, new), "migrate")  # date unknown: migrate to be safe
		self.assertEqual(act(old, new, s="16.53.0"), "refuse")  # v16 snapshot on a develop bench
		self.assertEqual(act(old, new, b="16.53.0"), "refuse")  # develop snapshot on a v16 bench


class TestBuildHelpers(UnitTestCase):
	def test_company_matches_a_live_install(self):
		"""The snapshot's wizard company has the name a live install of the same seed would pick."""
		name, abbr = snapshot.company_identity("furniture_store", 1)
		self.assertEqual(name, "Indigo Brass Home Studio Pvt Ltd")
		self.assertTrue(abbr.isupper())

	def test_fiscal_year(self):
		self.assertEqual(snapshot.fiscal_year(dt.date(2026, 11, 9)), (dt.date(2026, 4, 1), dt.date(2027, 3, 31)))
		self.assertEqual(snapshot.fiscal_year(dt.date(2027, 2, 1)), (dt.date(2026, 4, 1), dt.date(2027, 3, 31)))

	def test_manifest_path(self):
		self.assertEqual(snapshot.manifest_path("/x/demo-a.sql.gz"), "/x/demo-a.json")


class TestTransientErrors(UnitTestCase):
	def test_frappe_wrapped_conflicts_are_transient(self):
		import frappe
		from pymysql.err import OperationalError

		from erpnext_demo_gen.writers import is_transient

		changed = OperationalError(1020, "Record has changed since last read in table 'tabStock Ledger Entry'")
		self.assertTrue(is_transient(changed))
		self.assertTrue(is_transient(frappe.QueryDeadlockError(changed)))  # how frappe raises it
		self.assertTrue(is_transient(frappe.QueryTimeoutError(OperationalError(1205, "Lock wait timeout"))))
		wrapped = RuntimeError("outer")
		wrapped.__cause__ = changed
		self.assertTrue(is_transient(wrapped))
		self.assertFalse(is_transient(frappe.ValidationError("Negative stock")))
		self.assertFalse(is_transient(OperationalError(1146, "Table doesn't exist")))
