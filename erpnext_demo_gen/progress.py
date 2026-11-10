"""Time estimates and progress lines for long commands (install, uninstall).

Rates are measured on a laptop with MariaDB in Docker (design doc 6.3); they
grow with database size, so estimates are rough by design.
"""

import time

PROGRESS_EVERY = 20  # seconds between progress lines


def duration(seconds: float) -> str:
	seconds = max(0, int(seconds))
	if seconds < 90:
		return f"{seconds} s"
	if seconds < 5400:
		return f"{round(seconds / 60)} min"
	return f"{seconds / 3600:.1f} h"


def install_seconds(documents: int) -> float:
	"""About 0.22 s per document on a small database, 0.31 s at Medium size."""
	return documents * (0.22 if documents < 5000 else 0.31)


def remove_seconds(documents: int, one_by_one: bool) -> float:
	"""Tier B (company-wide deletion) is fast; tier A removes documents one by one."""
	return documents * 0.25 if one_by_one else 15 + documents * 0.006


class Progress:
	"""Prints "done of total (pct), elapsed, about N left" at most every PROGRESS_EVERY seconds."""

	def __init__(self, total: int, log, verb: str):
		self.total, self.log, self.verb = total, log, verb
		self.started = self.last = time.monotonic()

	def update(self, done: int):
		now = time.monotonic()
		if now - self.last < PROGRESS_EVERY or not self.total:
			return
		self.last = now
		elapsed = now - self.started
		left = elapsed / done * (self.total - done) if done else 0
		pct = 100 * done // self.total
		self.log(
			f"  {done} of {self.total} {self.verb} ({pct}%), {duration(elapsed)} so far, about {duration(left)} left"
		)
