"""Work around orphaned tax-template rows (finding F-26).

Company.on_trash deletes a company's Sales/Purchase Taxes and Charges Templates
and Item Tax Templates with raw SQL, leaving their child rows behind. When a
company with the same abbreviation is created later, india_compliance creates
templates with the same names and the orphans reattach, so every tax row
appears twice (or more) and GST is charged twice.
"""

import frappe

TEMPLATE_TABLES = (
	("Sales Taxes and Charges Template", "Sales Taxes and Charges"),
	("Purchase Taxes and Charges Template", "Purchase Taxes and Charges"),
	("Item Tax Template", "Item Tax Template Detail"),
)


def delete_template_rows(company: str):
	"""Before deleting a company: remove the child rows its on_trash would orphan."""
	for parent_doctype, child_doctype in TEMPLATE_TABLES:
		names = frappe.get_all(parent_doctype, filters={"company": company}, pluck="name")
		if names:
			frappe.db.delete(child_doctype, {"parenttype": parent_doctype, "parent": ["in", names]})


def purge_orphans(abbr: str) -> int:
	"""Before creating a company: drop orphaned rows that templates named '... - <abbr>' would adopt."""
	removed = 0
	for parent_doctype, child_doctype in TEMPLATE_TABLES:
		parents = frappe.db.sql_list(
			f"""select distinct c.parent from `tab{child_doctype}` c
			left join `tab{parent_doctype}` t on t.name = c.parent
			where c.parenttype = %s and c.parent like %s and t.name is null""",
			(parent_doctype, f"% - {abbr}"),
		)
		for parent in parents:
			removed += frappe.db.count(child_doctype, {"parenttype": parent_doctype, "parent": parent})
			frappe.db.delete(child_doctype, {"parenttype": parent_doctype, "parent": parent})
	return removed
