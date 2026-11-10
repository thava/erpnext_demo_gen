from frappe.tests import UnitTestCase

from erpnext_demo_gen.tests.golden_plans import CASES, compare


class TestGoldenPlans(UnitTestCase):
	"""The planner's output must not change unless a change is intended (then re-freeze)."""

	def test_plans_match_golden_files(self):
		failures = [report for name in CASES if (report := compare(name))]
		self.assertFalse(failures, "\n\n".join(failures))
