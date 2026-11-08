"""Writers execute a plan against the site (design 5.6).

ApiWriter (tier 1) goes through ERPNext's own insert and submit paths, one
document per transaction, committed together with its registry row (M-8). A
failure rolls back only that document and is recorded as Failed with its error;
dependants are recorded as Skipped (skip-and-log, M-12); transient database
conflicts are retried. Documents already in the registry are skipped, so a
re-run resumes.
"""

import time
import traceback
from dataclasses import dataclass, field
from datetime import date

import frappe
from frappe.utils import getdate

from demo_data.planner import PlannedDoc
from demo_data.registry import Run


class WriterAborted(Exception):
	pass


@dataclass
class WriteContext:
	"""Site facts the builders need, resolved once per run."""

	company: str
	abbr: str
	default_warehouse: str
	start_date: date
	territory: str
	selling_price_list: str
	buying_price_list: str
	tax_templates: dict = field(default_factory=dict)  # gst rate -> Item Tax Template
	gst_registered: bool = True  # False with --no-gst: no GST on sales, purchase GST is a cost
	home_state_code: str = ""
	bank_account: str = ""  # the demo's main Bank Account and its ledger (setup_banking)
	bank_ledger: str = ""
	cash_account: str = ""
	accounts: dict = field(default_factory=dict)  # role (main, collection) -> {ledger, bank_account}

	@classmethod
	def for_run(cls, run: Run, pack: dict, start_date: date) -> "WriteContext":
		from frappe.utils.nestedset import get_root_of

		from demo_data.india.geo import state_code

		company = run.doc.company
		abbr = frappe.get_cached_value("Company", company, "abbr")
		templates = {}
		for row in frappe.get_all(
			"Item Tax Template",
			filters={"company": company, "disabled": 0, "gst_rate": [">", 0]},
			fields=["name", "gst_rate"],
			order_by="name",
		):
			templates.setdefault(float(row.gst_rate), row.name)
		return cls(
			company=company,
			abbr=abbr,
			default_warehouse=f"{pack['company']['warehouses'][0]} - {abbr}",
			start_date=getdate(start_date),
			territory="India" if frappe.db.exists("Territory", "India") else get_root_of("Territory"),
			selling_price_list=frappe.db.get_single_value("Selling Settings", "selling_price_list")
			or "Standard Selling",
			buying_price_list=frappe.db.get_single_value("Buying Settings", "buying_price_list")
			or "Standard Buying",
			tax_templates=templates,
			gst_registered=run.params.get("gst", "registered") == "registered",
			home_state_code=state_code(run.params.home_state),
			bank_account=(run.params.get("banking") or {}).get("bank_account", ""),
			bank_ledger=(run.params.get("banking") or {}).get("bank_ledger")
			or frappe.get_cached_value("Company", company, "default_bank_account"),
			cash_account=frappe.get_cached_value("Company", company, "default_cash_account"),
			accounts=(run.params.get("banking") or {}).get("accounts") or {},
		)

	def item_tax_template(self, rate) -> str:
		try:
			return self.tax_templates[float(rate)]
		except KeyError:
			frappe.throw(f"No Item Tax Template with GST rate {rate}% for {self.company}")


def resolve(value, done: dict):
	"""Replace {"$ref": key} with the document name the key produced."""
	if isinstance(value, dict):
		if set(value) == {"$ref"}:
			return done[value["$ref"]]
		return frappe._dict({k: resolve(v, done) for k, v in value.items()})
	if isinstance(value, list):
		return [resolve(v, done) for v in value]
	return value


RETRIES = 6  # waits 2, 4, 8, 16 and 32 s between attempts (about a minute in all)


def is_transient(error: Exception) -> bool:
	"""Errors where MariaDB aborted the transaction because of another connection
	(deadlock, lock wait timeout, or "Record has changed since last read", 1020);
	the same document usually succeeds when written again."""
	if frappe.db.is_deadlocked(error) or frappe.db.is_timedout(error):
		return True
	args = getattr(error, "args", ())
	return bool(args) and args[0] == 1020


class ApiWriter:
	"""Writes one document per transaction.

	Batched commits with savepoints did not survive MariaDB aborting a transaction
	when a background worker touched the same rows (F-34): the savepoint vanished
	with it. One document per commit costs little next to the ~0.2 s a document
	takes, keeps every committed document registered, and makes a retry safe.
	"""

	def __init__(self, run: Run, wctx: WriteContext, max_failures: int | None = None, log=print):
		self.run, self.wctx, self.log = run, wctx, log
		self.max_failures = max_failures
		self.stats = {"created": 0, "reused": 0, "failed": 0, "skipped": 0, "already": 0, "retried": 0}

	def build(self, pd: PlannedDoc, done: dict):
		from demo_data.writers import builders

		for attempt in range(1, RETRIES + 1):
			try:
				return getattr(builders, pd.builder)(resolve(pd.params, done), self.wctx, pd)
			except Exception as e:
				frappe.db.rollback()
				frappe.local.message_log = []
				if attempt < RETRIES and is_transient(e):
					self.stats["retried"] += 1
					time.sleep(2**attempt)
					continue
				raise

	def execute(self, plan: list[PlannedDoc]):
		done = self.run.done_map()
		max_failures = self.max_failures if self.max_failures is not None else max(5, len(plan) // 50)
		from demo_data.progress import Progress

		started = time.monotonic()
		progress = Progress(sum(1 for pd in plan if pd.key not in done), self.log, "documents written")
		written = 0

		for pd in plan:
			if pd.key in done:
				self.stats["already"] += 1
				continue
			blocked = [k for k in pd.depends_on if k not in done]
			if blocked:
				self.run.record(pd.key, pd.doctype, None, "Skipped", f"depends on {', '.join(blocked)}")
				frappe.db.commit()
				self.stats["skipped"] += 1
				continue

			try:
				doc = self.build(pd, done)
			except Exception as e:
				self.run.record(
					pd.key,
					pd.doctype,
					None,
					"Failed",
					f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}",
				)
				frappe.db.commit()
				self.stats["failed"] += 1
				self.log(f"  failed {pd.key}: {type(e).__name__}: {str(e)[:200]}")
				if self.stats["failed"] > max_failures:
					raise WriterAborted(
						f"{self.stats['failed']} documents failed (limit {max_failures}); see Demo Data Record errors"
					) from e
				continue

			state = (
				"Reused"
				if doc.flags.get("demo_reused")
				else {0: "Created", 1: "Submitted", 2: "Cancelled"}[doc.docstatus]
			)
			self.run.record(pd.key, doc.doctype, doc.name, state)
			frappe.db.commit()
			done[pd.key] = doc.name
			self.stats["reused" if state == "Reused" else "created"] += 1
			written += 1
			progress.update(written)

		frappe.db.commit()
		self.stats["seconds"] = round(time.monotonic() - started, 1)
		return self.stats
