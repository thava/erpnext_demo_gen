"""Writers execute a plan against the site (design 5.6).

ApiWriter (tier 1) goes through ERPNext's own insert and submit paths. Each
document runs inside a savepoint: a failure rolls back only that document, is
recorded as Failed with its error, and dependants are recorded as Skipped
(skip-and-log, M-12). Commits happen in batches together with the registry rows
(M-8). Documents already in the registry are skipped, so a re-run resumes.
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

	@classmethod
	def for_run(cls, run: Run, pack: dict, start_date: date) -> "WriteContext":
		from frappe.utils.nestedset import get_root_of

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


class ApiWriter:
	def __init__(
		self, run: Run, wctx: WriteContext, batch_size: int = 50, max_failures: int | None = None, log=print
	):
		self.run, self.wctx, self.batch_size, self.log = run, wctx, batch_size, log
		self.max_failures = max_failures
		self.stats = {"created": 0, "reused": 0, "failed": 0, "skipped": 0, "already": 0}

	def execute(self, plan: list[PlannedDoc]):
		from demo_data.writers import builders

		done = self.run.done_map()
		unavailable: set[str] = set()
		max_failures = self.max_failures if self.max_failures is not None else max(5, len(plan) // 50)
		pending, started = 0, time.monotonic()

		for pd in plan:
			if pd.key in done:
				self.stats["already"] += 1
				continue
			blocked = [k for k in pd.depends_on if k not in done]
			if blocked:
				self.run.record(pd.key, pd.doctype, None, "Skipped", f"depends on {', '.join(blocked)}")
				unavailable.add(pd.key)
				self.stats["skipped"] += 1
				continue

			savepoint = f"dd_{pd.seq}"
			frappe.db.savepoint(savepoint)
			try:
				doc = getattr(builders, pd.builder)(resolve(pd.params, done), self.wctx, pd)
			except Exception as e:
				frappe.db.rollback(save_point=savepoint)
				frappe.local.message_log = []
				self.run.record(
					pd.key,
					pd.doctype,
					None,
					"Failed",
					f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=4)}",
				)
				unavailable.add(pd.key)
				self.stats["failed"] += 1
				self.log(f"  failed {pd.key}: {type(e).__name__}: {str(e)[:200]}")
				if self.stats["failed"] > max_failures:
					frappe.db.commit()
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
			done[pd.key] = doc.name
			self.stats["reused" if state == "Reused" else "created"] += 1
			pending += 1
			if pending >= self.batch_size:
				frappe.db.commit()
				pending = 0
				self.log(f"  {self.stats['created']} created, {time.monotonic() - started:.0f}s")

		frappe.db.commit()
		self.stats["seconds"] = round(time.monotonic() - started, 1)
		return self.stats
