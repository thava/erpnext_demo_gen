"""Golden plans: the planner's exact output for fixed cases, saved as digests.

A refactor that should not change behaviour (such as the locale layer) must leave
these identical. Each case is stored as one line per planned document:

    <seq> <key> <sha256 of doctype, builder, dates, depends_on and params>

Freeze (only when a change of output is intended, and say so in the commit):
    bench --site demo-data.localhost execute demo_data.tests.golden_plans.freeze

Check: test_golden_plans.py, run by `bench run-tests --app demo_data`.
"""

import datetime as dt
import hashlib
import json
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden"
END = dt.date(2026, 11, 8)

# name: (pack, size, seed, home_state, sales_tax)
CASES = {
	"furniture_store-micro-s1": ("furniture_store", "micro", 1, "Tamil Nadu", True),
	"furniture_store-small-s2": ("furniture_store", "small", 2, "Tamil Nadu", True),
	"furniture_store-small-s3-nogst": ("furniture_store", "small", 3, "Tamil Nadu", False),
	"electrical_distributor-micro-s4-mh": ("electrical_distributor", "micro", 4, "Maharashtra", True),
	"electrical_distributor-small-s5": ("electrical_distributor", "small", 5, "Karnataka", True),
	"electrical_distributor-medium-s6": ("electrical_distributor", "medium", 6, "Tamil Nadu", True),
	"furniture_store_us-micro-s7": ("furniture_store_us", "micro", 7, "Texas", True),
	"furniture_store_us-small-s8": ("furniture_store_us", "small", 8, "Texas", True),
}


def plan_case(name: str) -> list:
	from demo_data.packs import load_pack
	from demo_data.planner import PlanContext, make_plan
	from demo_data.setup.company import date_range

	pack_id, size, seed, home, sales_tax = CASES[name]
	pack = load_pack(pack_id)
	start, end = date_range(END, pack["sizes"][size]["months"])
	ctx = PlanContext(pack, size, seed, home, start, end, sales_tax)
	return make_plan(ctx)


def digest_lines(docs: list) -> list[str]:
	lines = []
	for d in docs:
		body = json.dumps(
			{
				"doctype": d.doctype,
				"builder": d.builder,
				"posting_date": d.posting_date,
				"posting_time": d.posting_time,
				"depends_on": d.depends_on,
				"params": d.params,
			},
			sort_keys=True,
			default=str,
		)
		lines.append(f"{d.seq} {d.key} {hashlib.sha256(body.encode()).hexdigest()[:16]}")
	return lines


def path_for(name: str) -> Path:
	return GOLDEN_DIR / f"{name}.txt"


def freeze(names: list[str] | None = None):
	"""Write the golden files for every case (or the named ones)."""
	GOLDEN_DIR.mkdir(exist_ok=True)
	for name in names or CASES:
		lines = digest_lines(plan_case(name))
		path_for(name).write_text("\n".join(lines) + "\n")
		print(f"{name}: {len(lines)} documents -> {path_for(name).name}")


def compare(name: str) -> str | None:
	"""None when the current plan matches the golden file, else a short description."""
	expected = path_for(name).read_text().splitlines()
	actual = digest_lines(plan_case(name))
	if actual == expected:
		return None
	diffs = [(e, a) for e, a in zip(expected, actual, strict=False) if e != a]  # lengths may differ
	report = [f"{name}: {len(expected)} documents expected, {len(actual)} planned"]
	for e, a in diffs[:5]:
		report.append(f"  expected {e}\n  got      {a}")
	if len(diffs) > 5:
		report.append(f"  ... {len(diffs) - 5} more differing lines")
	return "\n".join(report)
