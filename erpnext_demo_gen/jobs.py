"""Keep generation from flooding the background queue.

Deleting a document enqueues frappe.model.delete_doc.delete_dynamic_links, one
job per document. Uninstall deletes hundreds, and with no worker running the
queue reaches its limit (frappe raises QueueOverloaded at about 500 jobs), which
then breaks every later enqueue on the site. The job only deletes a few rows,
so we run it inline instead.
"""

import sys
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


# ---------------------------------------------------------------- desk page jobs (design 5.19)
# Install and uninstall from the DemoGen page run as one long-queue job per site. The job
# calls the same service functions as the CLI; its live state (latest progress and log
# lines) is kept in the Redis cache, not the database, so writing it never commits the
# install's transaction, and published to the page as it changes.

JOB_ID = "demo-gen"  # one job per site: frappe namespaces job ids by site
LIVE_KEY = "demo_gen:live"
REALTIME_EVENT = "demo_gen_progress"
JOB_TIMEOUT = 3600  # medium takes about 5 minutes; small and medium only from the page
PUBLISH_EVERY = 1.0  # seconds between progress messages to the page
KEEP_LINES = 40


def job_status() -> str | None:
	"""queued, started, finished, failed, ... or None (no job, or it expired)."""
	from frappe.utils.background_jobs import get_job_status

	status = get_job_status(JOB_ID)
	return str(status.value if hasattr(status, "value") else status) if status else None


def job_active() -> bool:
	return job_status() in ("queued", "started", "deferred", "scheduled")


def long_queue_workers() -> int:
	from frappe.utils.background_jobs import get_queue, get_workers

	try:
		return len(get_workers(queue=get_queue("long")))
	except Exception:
		return 0


def get_live() -> dict:
	return frappe.cache.get_value(LIVE_KEY) or {}


def set_live(state: dict, publish: bool = True):
	state["updated_at"] = frappe.utils.now()
	frappe.cache.set_value(LIVE_KEY, state, expires_in_sec=7 * 24 * 3600)
	if publish:
		frappe.publish_realtime(REALTIME_EVENT, state, user=state.get("user"), after_commit=False)


def enqueue(action: str, method: str, live_run: str | None = None, **kwargs):
	"""Queue a page job unless one is queued or running; record it as the live state."""
	from erpnext_demo_gen.service import DemoDataError

	if job_active():
		raise DemoDataError("A DemoGen job is already queued or running on this site; wait for it to finish")
	set_live(
		{
			"action": action,
			"status": "queued",
			"user": frappe.session.user,
			"queued_at": frappe.utils.now(),
			"lines": [],
			"run": live_run,
		}
	)
	frappe.enqueue(method, queue="long", timeout=JOB_TIMEOUT, job_id=JOB_ID, deduplicate=True, **kwargs)


class _JobLog:
	"""The log function for service calls in a job: keeps the last lines and the structured
	progress in the live state, and publishes them to the page at most every PUBLISH_EVERY s."""

	def __init__(self, state: dict):
		import time

		self.state, self.time, self.last = state, time.monotonic, 0.0

	def __call__(self, line: str):
		line = str(line)
		print(line)  # the worker log
		self.state["lines"] = (self.state.get("lines") or [])[-(KEEP_LINES - 1):] + [line]
		self.state["message"] = line.strip()
		self.publish(force=True)

	def progress(self, done: int, total: int, verb: str, left):
		self.state.update(done=done, total=total, verb=verb, left=None if left is None else round(left))
		self.publish()

	def publish(self, force: bool = False):
		now = self.time()
		if force or now - self.last >= PUBLISH_EVERY:
			self.last = now
			set_live(self.state)


def stale_code_files() -> list[str]:
	"""The app's loaded modules whose source changed after this process loaded them: a worker
	started before an update keeps old modules, and the jobs it forks inherit them."""
	import os

	import erpnext_demo_gen

	stale = []
	for name, loaded_at in list(erpnext_demo_gen.LOADED_AT.items()):
		path = getattr(sys.modules.get(name), "__file__", None)
		if path and os.path.exists(path) and os.path.getmtime(path) > loaded_at + 1:
			stale.append(name)
	return sorted(stale)


def _run_job(action: str, fn):
	from erpnext_demo_gen.progress import listening
	from erpnext_demo_gen.service import DemoDataError

	state = get_live()
	if state.get("action") != action:  # started some other way (a test, bench execute)
		state = {"action": action, "user": frappe.session.user}
	state.update(status="running", started_at=frappe.utils.now(), lines=[], error=None, done=None, total=None)
	log = _JobLog(state)
	log.publish(force=True)
	stale = stale_code_files()
	if stale:
		state.update(
			status="failed",
			finished_at=frappe.utils.now(),
			error="The background worker is running an older version of DemoGen (changed since it "
			f"started: {', '.join(stale[:5])}{' ...' if len(stale) > 5 else ''}). Restart the workers "
			"(bench restart; in development, restart bench start), then try again.",
		)
		set_live(state)
		return
	try:
		with listening(log.progress):
			run = fn(log)
		done = "installed" if action == "install" else "uninstalled"
		state.update(status="done", run=run.name, finished_at=frappe.utils.now(), message=f"{run.name} {done} ({run.doc.company})")
	except DemoDataError as e:
		state.update(status="failed", error=str(e), finished_at=frappe.utils.now())
	except Exception as e:
		frappe.log_error(f"DemoGen {action} job")
		state.update(status="failed", error=f"{type(e).__name__}: {e}", finished_at=frappe.utils.now())
	set_live(state)


def install_job(**options):
	"""Install from the page: service.install with the options start_install checked."""
	from erpnext_demo_gen import service

	_run_job("install", lambda log: service.install(log=log, **options))


def uninstall_job(run_name: str):
	from erpnext_demo_gen import service

	_run_job("uninstall", lambda log: service.uninstall(run_name, log=log))
