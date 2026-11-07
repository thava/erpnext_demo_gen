"""Keep generation from flooding the background queue.

Deleting a document enqueues frappe.model.delete_doc.delete_dynamic_links, one
job per document. Uninstall deletes hundreds, and with no worker running the
queue reaches its limit (frappe raises QueueOverloaded at about 500 jobs), which
then breaks every later enqueue on the site. The job only deletes a few rows,
so we run it inline instead.
"""

from collections import Counter
from contextlib import contextmanager

import frappe

INLINE_JOBS = {"frappe.model.delete_doc.delete_dynamic_links"}


def _job_name(method) -> str:
	return method if isinstance(method, str) else f"{method.__module__}.{method.__qualname__}"


@contextmanager
def inline_jobs(names=INLINE_JOBS):
	"""Run the named background jobs immediately; count every enqueue for reporting."""
	original = frappe.enqueue
	counts: Counter = Counter()

	def enqueue(method, *args, **kwargs):
		name = _job_name(method)
		counts[name] += 1
		if name in names:
			kwargs["now"] = True
			kwargs.pop("enqueue_after_commit", None)
		return original(method, *args, **kwargs)

	frappe.enqueue = enqueue
	try:
		yield counts
	finally:
		frappe.enqueue = original
