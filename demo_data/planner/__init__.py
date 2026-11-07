"""Planner: pack + size + seed + dates -> an ordered list of PlannedDoc (design 5.4).

Pure: no database access, so the plan is deterministic and unit-testable (M-5).
Documents refer to each other through plan keys ({"$ref": key}); the writer
resolves them to real document names. Each concern draws from its own random
stream (ctx.rng("purpose")), so changing one part of the plan never reshuffles
another.
"""

import random
from dataclasses import dataclass, field
from datetime import date


class PlanError(Exception):
	pass


@dataclass
class PlannedDoc:
	key: str  # deterministic, e.g. "M:item:SOFA-001"; registry plan_key
	seq: int  # global order
	doctype: str
	builder: str  # name of a function in demo_data.writers.builders
	params: dict  # everything needed to build; may contain {"$ref": key}
	depends_on: list[str] = field(default_factory=list)
	posting_date: date | None = None
	posting_time: str | None = None  # "HH:MM:SS"; strictly increasing within a day


def ref(key: str) -> dict:
	return {"$ref": key}


def refs_in(value) -> list[str]:
	"""Every plan key referenced anywhere inside params."""
	if isinstance(value, dict):
		if set(value) == {"$ref"}:
			return [value["$ref"]]
		return [k for v in value.values() for k in refs_in(v)]
	if isinstance(value, list):
		return [k for v in value for k in refs_in(v)]
	return []


@dataclass
class PlanContext:
	pack: dict
	size_name: str
	seed: int
	home_state: str
	start_date: date
	end_date: date

	@property
	def size(self) -> dict:
		return self.pack["sizes"][self.size_name]

	def rng(self, purpose: str) -> random.Random:
		return random.Random(f"{self.seed}:{purpose}")


class Plan:
	def __init__(self, ctx: PlanContext):
		self.ctx = ctx
		self.docs: list[PlannedDoc] = []
		self.keys: set[str] = set()

	def add(
		self,
		key: str,
		doctype: str,
		builder: str,
		params: dict,
		posting_date: date | None = None,
		posting_time: str | None = None,
	) -> str:
		if key in self.keys:
			raise PlanError(f"duplicate plan key {key}")
		depends = refs_in(params)
		missing = [k for k in depends if k not in self.keys]
		if missing:
			raise PlanError(f"{key} refers to keys not planned before it: {missing}")
		self.docs.append(
			PlannedDoc(key, len(self.docs) + 1, doctype, builder, params, depends, posting_date, posting_time)
		)
		self.keys.add(key)
		return key


def make_plan(ctx: PlanContext) -> list[PlannedDoc]:
	from demo_data.planner.masters import plan_masters

	plan = Plan(ctx)
	plan_masters(plan)
	from demo_data.planner.transactions import plan_transactions

	plan_transactions(plan)
	return plan.docs
