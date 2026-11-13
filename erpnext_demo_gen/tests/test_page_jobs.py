"""The desk page's jobs (design 5.19), run inline: no worker needed.

install_job and uninstall_job call the same service functions as the CLI; this checks what
the page relies on: the live state (status, progress, log lines), the run, and the registry.
It commits (an install always does) and removes what it created, like the smoke test.
"""

import frappe
from frappe.tests import UnitTestCase

from erpnext_demo_gen import jobs
from erpnext_demo_gen.registry import Run, active_runs


def country_for_site() -> str:
	return "IN" if "india_compliance" in frappe.get_installed_apps() else "US"


class TestNeedsForce(UnitTestCase):
	def test_cli_message_and_page_question(self):
		from erpnext_demo_gen.service import NeedsForce

		e = NeedsForce("This site already has transactions:\n  A: 1 document", "Installing needs --force.", "Install anyway?")
		self.assertIn("--force", str(e))
		self.assertNotIn("--force", e.reason)
		self.assertEqual(e.question, "Install anyway?")


class TestPageJobs(UnitTestCase):
	def test_install_and_uninstall_jobs(self):
		if active_runs():
			self.skipTest("a demo run is installed on this site; the test needs none")
		jobs.set_live({"action": "install", "status": "queued", "user": frappe.session.user, "lines": []}, publish=False)
		jobs.install_job(country=country_for_site(), size="small", seed=5, force=True)

		live = jobs.get_live()
		self.assertEqual(live.get("status"), "done", live.get("error"))
		self.assertTrue(live.get("run"))
		self.assertTrue(live.get("lines"))
		self.assertEqual(live.get("done"), live.get("total"))
		self.assertEqual(live.get("verb"), "documents written")
		run = Run(live["run"])
		self.assertEqual(run.doc.status, "Completed")
		self.assertGreater(run.totals().get("Submitted", 0), 50)

		from erpnext_demo_gen import api

		state = api.get_state()
		self.assertEqual([r.name for r in state["runs"]], [run.name])
		self.assertFalse(state["runs"][0].stopped)

		jobs.uninstall_job(run_name=run.name)
		live = jobs.get_live()
		self.assertEqual(live.get("status"), "done", live.get("error"))
		self.assertEqual(live.get("action"), "uninstall")
		self.assertEqual(frappe.db.get_value("Demo Data Run", run.name, "status"), "Uninstalled")

	def test_a_failure_is_reported_not_raised(self):
		jobs.install_job(country="XX", size="small", seed=1, force=True)
		live = jobs.get_live()
		self.assertEqual(live.get("status"), "failed")
		self.assertIn("XX", live.get("error") or "")
