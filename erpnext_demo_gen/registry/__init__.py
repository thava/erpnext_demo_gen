"""Registry: Demo Data Run (one per install) and Demo Data Record (one per created document).

Every document the app creates goes through `Run.ensure`, which skips plan keys
already recorded (resume) and writes the record in the same transaction as the
document (M-8), so a crash loses both or neither.
"""

import json
import traceback
from collections.abc import Callable

import frappe
from frappe.utils import now_datetime

ACTIVE_STATUSES = ("Planned", "Running", "Failed", "Completed", "Uninstalling")
RESUMABLE_STATUSES = ("Planned", "Running", "Failed")
DONE_STATES = ("Created", "Submitted")
# a plan key is satisfied by a document the run created or by an existing one it reused
RESOLVED_STATES = (*DONE_STATES, "Cancelled", "Reused")


def app_versions() -> dict:
	versions = {}
	for app in ("frappe", "erpnext", "india_compliance", "erpnext_demo_gen"):
		try:
			versions[app] = frappe.get_attr(f"{app}.__version__")
		except Exception:
			versions[app] = None
	return versions


def active_runs() -> list[dict]:
	return frappe.get_all(
		"Demo Data Run",
		filters={"status": ["in", ACTIVE_STATUSES]},
		fields=["name", "status", "pack", "size", "seed", "end_date", "company", "params"],
		order_by="creation asc",
	)


def demo_companies() -> list[str]:
	return [r.company for r in active_runs() if r.company]


class Run:
	def __init__(self, name: str):
		self.doc = frappe.get_doc("Demo Data Run", name)
		self.params = frappe._dict(json.loads(self.doc.params or "{}"))
		self._seq = (
			frappe.db.sql("select max(seq) from `tabDemo Data Record` where run=%s", (name,))[0][0] or 0
		)

	@property
	def name(self) -> str:
		return self.doc.name

	@classmethod
	def create(cls, params: dict) -> "Run":
		doc = frappe.get_doc(
			{
				"doctype": "Demo Data Run",
				"status": "Planned",
				"pack": params["pack"],
				"pack_version": params["pack_version"],
				"size": params["size"],
				"seed": params["seed"],
				"end_date": params["end_date"],
				"company": params.get("company"),
				"params": json.dumps(params, indent=1, default=str),
				"app_versions": json.dumps(app_versions(), indent=1),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		return cls(doc.name)

	# ------------------------------------------------------------ status
	def set_status(self, status: str, error: str | None = None, totals: bool = False, **values):
		"""Change status and append an event to the run's history (see events()).

		totals adds the run's document count per state to the event, e.g. how many
		were created on install or deleted and kept on uninstall.
		"""
		now = now_datetime()
		values = {"status": status, **values}
		if status == "Running" and not self.doc.started_at:
			values["started_at"] = now
		if status in ("Completed", "Failed", "Uninstalled"):
			values["finished_at"] = now
		if error is not None:
			values["error"] = error
		event = {"at": str(now.replace(microsecond=0)), "status": status}
		if totals:
			event["documents"] = self.totals()
		if error:
			lines = error.strip().splitlines()
			event["error"] = (lines[-1] if lines[0].startswith("Traceback") else lines[0])[:200]
		values["events"] = json.dumps([*self.events(), event], indent=1)
		self.doc.db_set(values)
		frappe.db.commit()

	def events(self) -> list[dict]:
		return frappe.parse_json(self.doc.get("events") or "[]")

	def totals(self) -> dict:
		"""Documents per state across all doctypes, e.g. {"Submitted": 850, "Created": 150}."""
		out: dict = {}
		for states in self.counts().values():
			for state, n in states.items():
				out[state] = out.get(state, 0) + n
		return out

	def update_params(self, **values):
		self.params.update(values)
		self.doc.db_set("params", json.dumps(self.params, indent=1, default=str))

	def set_company(self, company: str):
		self.update_params(company=company)
		self.doc.db_set("company", company)

	# ------------------------------------------------------------ records
	def get_record(self, plan_key: str):
		return frappe.db.get_value(
			"Demo Data Record",
			{"run": self.name, "plan_key": plan_key, "state": ["in", DONE_STATES]},
			["name", "ref_doctype", "ref_name", "state"],
			as_dict=True,
		)

	def record(self, plan_key: str, doctype: str, name: str | None, state: str, error: str | None = None):
		self._seq += 1
		frappe.get_doc(
			{
				"doctype": "Demo Data Record",
				"run": self.name,
				"seq": self._seq,
				"plan_key": plan_key,
				"ref_doctype": doctype,
				"ref_name": name,
				"state": state,
				"error": (error or "")[:1000] or None,
			}
		).db_insert()

	def ensure(self, plan_key: str, create: Callable[[], "frappe.model.document.Document"]) -> str:
		"""Run `create` once per plan key; return the created (or previously created) document name.

		Commits the document together with its registry record. On error, rolls both
		back, records the failure and re-raises.
		"""
		existing = self.get_record(plan_key)
		if existing and frappe.db.exists(existing.ref_doctype, existing.ref_name):
			return existing.ref_name
		try:
			doc = create()
			self.record(plan_key, doc.doctype, doc.name, "Submitted" if doc.docstatus == 1 else "Created")
			frappe.db.commit()
			return doc.name
		except Exception as e:
			frappe.db.rollback()
			self.record(
				plan_key, "", None, "Failed", f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"
			)
			frappe.db.commit()
			raise

	def done_map(self) -> dict[str, str]:
		"""plan_key -> document name for every key already satisfied (used to resume and to resolve refs)."""
		rows = frappe.get_all(
			"Demo Data Record",
			filters={"run": self.name, "state": ["in", RESOLVED_STATES]},
			fields=["plan_key", "ref_doctype", "ref_name"],
			order_by="seq asc",
		)
		return {r.plan_key: r.ref_name for r in rows}

	def records(self, states=DONE_STATES, reverse=False) -> list[dict]:
		return frappe.get_all(
			"Demo Data Record",
			filters={"run": self.name, "state": ["in", states]},
			fields=["name", "seq", "plan_key", "ref_doctype", "ref_name", "state"],
			order_by=f"seq {'desc' if reverse else 'asc'}",
		)

	def set_record_state(self, record_name: str, state: str, error: str | None = None):
		frappe.db.set_value(
			"Demo Data Record",
			record_name,
			{"state": state, "error": (error or "")[:1000] or None},
			update_modified=False,
		)

	def gaps(self) -> list[str]:
		"""Plan keys that failed or were skipped and have not been satisfied since."""
		resolved = set(self.done_map())
		missing = frappe.get_all(
			"Demo Data Record",
			filters={"run": self.name, "state": ["in", ("Failed", "Skipped")], "plan_key": ["is", "set"]},
			pluck="plan_key",
			distinct=True,
		)
		return sorted(set(missing) - resolved)

	def counts(self) -> dict:
		"""Documents per doctype and state, counting each plan key once, by its latest record.

		A key can have several records (failed, then created on a resume); only the
		last one says where it stands now.
		"""
		rows = frappe.db.sql(
			"""select r.ref_doctype, r.state, count(*)
			from `tabDemo Data Record` r
			join (select plan_key, max(seq) seq from `tabDemo Data Record` where run=%s group by plan_key) last
				on last.plan_key = r.plan_key and last.seq = r.seq
			where r.run=%s and r.state != 'Cancelled'
			group by r.ref_doctype, r.state""",
			(self.name, self.name),
		)
		out: dict = {}
		for doctype, state, n in rows:
			out.setdefault(doctype or "(failed)", {})[state] = n
		return out
