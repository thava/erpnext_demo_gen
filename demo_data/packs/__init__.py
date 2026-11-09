"""Business packs: YAML files that describe a demo business.

load_pack(id) reads <id>.yaml from this folder, resolves `extends` (child keys
override the base; a list replaces the base list unless the child writes the key
with a trailing "+", which appends), validates the result, and returns a plain
dict. Validation is plain Python (no jsonschema dependency, C-3) and reports
every problem with its path, not just the first.
"""

import copy
import os
import string

import yaml

PACK_DIR = os.path.dirname(__file__)
SCHEMA_VERSION = 1
SIZES = ("micro", "small", "medium")
SIZE_KEYS = ("months", "customers", "suppliers", "items", "sales_invoices", "purchase_invoices")
FLOW_STEPS = ("quotation", "sales_order", "delivery_note", "sales_invoice", "payment_entry")
PAYMENT_TERMS = ("immediate", "net_15", "net_30", "net_45", "net_60")
PARTY_CLASSES = ("b2b", "b2c")


class PackError(Exception):
	def __init__(self, pack_id: str, errors: list[str]):
		self.pack_id, self.errors = pack_id, errors
		super().__init__(f"Pack {pack_id!r} is invalid:\n  - " + "\n  - ".join(errors))


# ---------------------------------------------------------------- loading
def list_packs(include_abstract: bool = False) -> list[dict]:
	packs = []
	for filename in sorted(os.listdir(PACK_DIR)):
		if filename.endswith(".yaml"):
			raw = _read(filename[:-5])
			if include_abstract or not raw.get("abstract"):
				packs.append(
					{"id": raw["id"], "title": raw.get("title"), "pack_version": raw.get("pack_version")}
				)
	return packs


def load_pack(pack_id: str) -> dict:
	pack = _resolve(pack_id, seen=())
	errors = validate_pack(pack)
	if errors:
		raise PackError(pack_id, errors)
	return pack


def _read(pack_id: str) -> dict:
	path = os.path.join(PACK_DIR, f"{pack_id}.yaml")
	if not os.path.exists(path):
		raise PackError(pack_id, [f"no pack file {path}"])
	with open(path) as f:
		data = yaml.safe_load(f) or {}
	if data.get("id") != pack_id:
		raise PackError(pack_id, [f"id {data.get('id')!r} does not match file name"])
	return data


def _resolve(pack_id: str, seen: tuple) -> dict:
	if pack_id in seen:
		raise PackError(pack_id, ["circular extends: " + " -> ".join((*seen, pack_id))])
	raw = _read(pack_id)
	base_id = raw.get("extends")
	if not base_id:
		return _strip_append_markers(copy.deepcopy(raw))
	merged = merge(_resolve(base_id, (*seen, pack_id)), raw)
	merged.pop("abstract", None)
	if raw.get("abstract"):
		merged["abstract"] = True
	return merged


def merge(base: dict, child: dict) -> dict:
	"""Child overrides base by key; nested dicts merge; "key+" appends to a base list."""
	out = copy.deepcopy(base)
	for key, value in child.items():
		if key.endswith("+"):
			key = key[:-1]
			out[key] = list(out.get(key) or []) + list(value)
		elif isinstance(value, dict) and isinstance(out.get(key), dict):
			out[key] = merge(out[key], value)
		else:
			out[key] = copy.deepcopy(value)
	return out


def _strip_append_markers(data):
	if isinstance(data, dict):
		return {k.rstrip("+"): _strip_append_markers(v) for k, v in data.items()}
	if isinstance(data, list):
		return [_strip_append_markers(v) for v in data]
	return data


# ---------------------------------------------------------------- validation
def validate_pack(pack: dict) -> list[str]:
	e: list[str] = []
	_check(e, pack.get("schema_version") == SCHEMA_VERSION, "schema_version", f"must be {SCHEMA_VERSION}")
	for key in ("id", "title"):
		_check(e, _is_str(pack.get(key)), key, "is required")
	_check(e, _is_int(pack.get("pack_version"), minimum=1), "pack_version", "must be a positive integer")
	from demo_data.locales import get_locale, known_locales

	code = pack.get("locale", "IN")
	if not _check(e, code in known_locales(), "locale", f"must be one of {', '.join(known_locales())}"):
		return e
	locale = get_locale(code)

	_validate_company(e, pack.get("company"))
	_validate_parties(e, pack.get("parties"))
	_validate_behavior(e, pack.get("behavior"))
	_validate_banking(e, pack.get("banking"), locale.payment_modes)
	_validate_sizes(e, pack.get("sizes"))
	if not pack.get("abstract"):
		_validate_channels(e, pack.get("channels"))
		_validate_catalog(e, pack.get("catalog"))
	locale.validate_pack(pack, lambda ok, path, message: _check(e, ok, path, message))
	return e


def _validate_company(e, company):
	if not _check(e, isinstance(company, dict), "company", "is required"):
		return
	nouns = company.get("industry_nouns")
	_check(
		e,
		isinstance(nouns, list) and nouns and all(map(_is_str, nouns)),
		"company.industry_nouns",
		"must be a non-empty list of words",
	)
	whs = company.get("warehouses")
	_check(
		e,
		isinstance(whs, list) and whs and all(map(_is_str, whs)),
		"company.warehouses",
		"must be a non-empty list of names",
	)
	funding = company.get("funding") or {}
	for key, value in funding.items():
		_check(e, _is_num(value, minimum=0), f"company.funding.{key}", "must be a non-negative number")


def _validate_parties(e, parties):
	if not _check(e, isinstance(parties, dict), "parties", "is required"):
		return
	for key in ("customer_nouns", "supplier_nouns"):
		nouns = parties.get(key)
		_check(
			e,
			isinstance(nouns, list) and nouns and all(map(_is_str, nouns)),
			f"parties.{key}",
			"must be a non-empty list of words",
		)
	groups = parties.get("customer_group") or {}
	_check(
		e,
		set(groups) == set(PARTY_CLASSES) and all(map(_is_str, groups.values())),
		"parties.customer_group",
		"needs b2b and b2c group names",
	)
	_check(e, _is_str(parties.get("supplier_group")), "parties.supplier_group", "is required")
	share = parties.get("supplier_home_state_share")
	_check(
		e, _is_num(share, 0) and share <= 1, "parties.supplier_home_state_share", "must be between 0 and 1"
	)


def template_fields(template: str) -> set[str]:
	return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _validate_channels(e, channels):
	if not _check(e, isinstance(channels, list) and channels, "channels", "must be a non-empty list"):
		return
	_check(e, _close(sum(c.get("share", 0) for c in channels), 1), "channels", "shares must add up to 1")
	for i, c in enumerate(channels):
		p = f"channels[{i}]"
		_check(e, _is_str(c.get("id")), f"{p}.id", "is required")
		_check(
			e, c.get("party_class") in PARTY_CLASSES, f"{p}.party_class", f"must be one of {PARTY_CLASSES}"
		)
		payment = c.get("payment") or {}
		_check(
			e,
			payment and set(payment) <= set(PAYMENT_TERMS),
			f"{p}.payment",
			f"keys must be among {PAYMENT_TERMS}",
		)
		_check(e, _close(sum(payment.values()), 1), f"{p}.payment", "shares must add up to 1")
		flow = c.get("flow") or []
		_check(e, flow and set(flow) <= set(FLOW_STEPS), f"{p}.flow", f"steps must be among {FLOW_STEPS}")
		_check(e, "sales_invoice" in flow, f"{p}.flow", "must include sales_invoice")
		for key in ("quantity", "lines"):
			if key in c:
				_check(
					e,
					_is_range(c[key], minimum=1) and all(_is_int(v) for v in c[key]),
					f"{p}.{key}",
					"must be [min, max] whole numbers >= 1",
				)


def _validate_catalog(e, catalog):
	if not _check(e, isinstance(catalog, dict), "catalog", "is required"):
		return
	groups = catalog.get("item_groups") or []
	_check(e, groups and all(map(_is_str, groups)), "catalog.item_groups", "must be a non-empty list")
	series = catalog.get("series") or []
	_check(
		e,
		all(map(_is_str, series)) and len(set(series)) == len(series),
		"catalog.series",
		"must be unique names",
	)
	families = catalog.get("families") or []
	if not _check(e, families, "catalog.families", "must be a non-empty list"):
		return
	ids = set()
	for i, f in enumerate(families):
		p = f"catalog.families[{i}]"
		fid = f.get("id")
		_check(e, _is_str(fid) and fid not in ids, f"{p}.id", "is required and must be unique")
		ids.add(fid)
		_check(e, f.get("group") in groups, f"{p}.group", f"{f.get('group')!r} is not in catalog.item_groups")
		template = f.get("name_template")
		if _check(e, _is_str(template), f"{p}.name_template", "is required"):
			options = f.get("options") or {}
			_check(
				e,
				isinstance(options, dict) and all(isinstance(v, list) and v for v in options.values()),
				f"{p}.options",
				"must map placeholder names to non-empty lists",
			)
			missing = template_fields(template) - {"series"} - set(options)
			_check(e, not missing, f"{p}.name_template", f"placeholders without options: {sorted(missing)}")
			if "series" in template_fields(template):
				_check(e, series, f"{p}.name_template", "uses {series} but catalog.series is empty")
		_check(e, _is_int(f.get("count"), minimum=1), f"{p}.count", "must be a positive integer")
		_check(
			e,
			_is_range(f.get("price_range"), minimum=1),
			f"{p}.price_range",
			"must be [low, high] with 0 < low <= high",
		)
		ratio = f.get("cost_ratio")
		_check(
			e,
			_is_range(ratio, minimum=0) and ratio[1] < 1,
			f"{p}.cost_ratio",
			"must be [low, high] between 0 and 1",
		)
		reorder = f.get("reorder") or {}
		_check(
			e,
			_is_int(reorder.get("min"), 0)
			and _is_int(reorder.get("max"), 1)
			and reorder["min"] <= reorder["max"],
			f"{p}.reorder",
			"needs integers min <= max",
		)


def _validate_behavior(e, behavior):
	if not _check(e, isinstance(behavior, dict), "behavior", "is required"):
		return
	index = (behavior.get("seasonality") or {}).get("monthly_index")
	_check(
		e,
		isinstance(index, list) and len(index) == 12 and all(_is_num(v, minimum=0) for v in index),
		"behavior.seasonality.monthly_index",
		"needs 12 non-negative numbers (April to March)",
	)
	share = (behavior.get("geography") or {}).get("home_state_share")
	_check(
		e, _is_num(share, 0) and share <= 1, "behavior.geography.home_state_share", "must be between 0 and 1"
	)
	for key in ("gst_categories", "payment_outcomes"):
		values = behavior.get(key) or {}
		_check(e, values and _close(sum(values.values()), 1), f"behavior.{key}", "shares must add up to 1")
	for key, value in (behavior.get("rates") or {}).items():
		_check(e, _is_num(value, 0) and value < 0.5, f"behavior.rates.{key}", "must be between 0 and 0.5")


PAYERS = ("counter", "customer", "supplier")


def _validate_banking(e, banking, payment_modes):
	if not _check(e, isinstance(banking, dict), "banking", "is required"):
		return
	for role in ("main", "collection"):
		bank = banking.get(role) or {}
		path = f"banking.{role}"
		if not _check(e, isinstance(bank, dict) and bank, path, "is required"):
			continue
		for key in ("bank", "short"):
			_check(e, _is_str(bank.get(key)), f"{path}.{key}", "is required")
	_check(e, _is_int(banking.get("sweep_weekday"), 0) and banking["sweep_weekday"] <= 6, "banking.sweep_weekday", "must be 0 (Monday) to 6")
	modes = banking.get("modes") or {}
	used = set()
	for payer in PAYERS:
		shares = modes.get(payer) or {}
		path = f"banking.modes.{payer}"
		if not _check(e, shares and _close(sum(shares.values()), 1), path, "shares must add up to 1"):
			continue
		for mode in shares:
			_check(e, mode in payment_modes, path, f"unknown mode {mode!r}; use {', '.join(payment_modes)}")
			_check(e, mode != "Cash" or payer == "counter", path, "Cash is only for counter payments")
		used |= set(shares)
	days = banking.get("clearing_days") or {}
	for mode in sorted(used - {"Cash"}):
		span = days.get(mode)
		_check(
			e,
			isinstance(span, list) and len(span) == 2 and all(_is_int(v) and v >= 0 for v in span) and span[0] <= span[1],
			f"banking.clearing_days.{mode}",
			"needs [min, max] days",
		)


def _validate_sizes(e, sizes):
	if not _check(e, isinstance(sizes, dict), "sizes", "is required"):
		return
	for size in SIZES:
		spec = sizes.get(size)
		if not _check(e, isinstance(spec, dict), f"sizes.{size}", "is required"):
			continue
		for key in SIZE_KEYS:
			_check(e, _is_int(spec.get(key), minimum=1), f"sizes.{size}.{key}", "must be a positive integer")


# ---------------------------------------------------------------- helpers
def _check(errors: list, ok, path: str, message: str) -> bool:
	if not ok:
		errors.append(f"{path}: {message}")
	return bool(ok)


def _is_str(v) -> bool:
	return isinstance(v, str) and bool(v.strip())


def _is_int(v, minimum=None) -> bool:
	return isinstance(v, int) and not isinstance(v, bool) and (minimum is None or v >= minimum)


def _is_num(v, minimum=None) -> bool:
	return isinstance(v, int | float) and not isinstance(v, bool) and (minimum is None or v >= minimum)


def _is_range(v, minimum=0) -> bool:
	"""[low, high] with minimum <= low <= high."""
	if not (isinstance(v, list) and len(v) == 2 and all(_is_num(x) for x in v)):
		return False
	return minimum <= v[0] <= v[1]


def _close(a, b) -> bool:
	return abs(a - b) < 1e-6
