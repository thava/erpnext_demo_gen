"""Definite dates from Frappe's converters, which are typed as "maybe None".

frappe.utils.getdate and get_datetime return None only for an empty or zero date
("0000-00-00"). The demo's dates are never that, so these helpers return a definite
value and fail loudly if one ever is.
"""

from datetime import date, datetime

from frappe.utils import get_datetime, getdate


def to_date(value) -> date:
	"""frappe.utils.getdate for a value known to be a date."""
	result = getdate(value)
	if result is None:
		raise ValueError(f"not a date: {value!r}")
	return result


def to_datetime(value) -> datetime:
	"""frappe.utils.get_datetime for a value known to be a date and time."""
	result = get_datetime(value)
	if result is None:
		raise ValueError(f"not a date and time: {value!r}")
	return result
