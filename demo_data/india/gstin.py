"""Fictional but checksum-valid PAN and GSTIN values.

A GSTIN is: 2-digit state code + 10-character PAN + entity number (1-9, A-Z)
+ "Z" + a check character. The check character uses the same algorithm as
india_compliance's validate_gstin_check_digit, so generated values pass it.
PAN has no public checksum; its fourth letter gives the holder type.
"""

import random
import string

CODE_POINTS = string.digits + string.ascii_uppercase  # 36 symbols

# PAN fourth letter by holder type
PAN_HOLDER_TYPES = {
	"company": "C",
	"person": "P",
	"firm": "F",
	"huf": "H",
	"trust": "T",
	"aop": "A",
}


def gstin_check_char(first14: str) -> str:
	factor, total = 1, 0
	for ch in first14:
		product = factor * CODE_POINTS.index(ch)
		total += product // 36 + product % 36
		factor = 2 if factor == 1 else 1
	return CODE_POINTS[(36 - total % 36) % 36]


def make_pan(rng: random.Random, holder_type: str = "company", name: str = "") -> str:
	"""PAN like ABCDE1234F: three letters, holder type, name initial, four digits, a letter."""
	letters = string.ascii_uppercase
	initial = next((c for c in name.upper() if c in letters), rng.choice(letters))
	return (
		"".join(rng.choice(letters) for _ in range(3))
		+ PAN_HOLDER_TYPES[holder_type]
		+ initial
		+ f"{rng.randint(1, 9999):04d}"
		+ rng.choice(letters)
	)


def make_gstin(state_code: str | int, pan: str, entity_number: int = 1) -> str:
	"""Regular-taxpayer GSTIN for a PAN registered in the given state."""
	first14 = f"{int(state_code):02d}{pan}{CODE_POINTS[entity_number]}Z"
	return first14 + gstin_check_char(first14)
