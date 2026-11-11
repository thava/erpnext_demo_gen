"""Curated word pools for clean, counter-free display names (DEC-10, DEC-18).

Company names have the shape [nature or colour word] [place or material word]
[industry noun] [legal suffix], e.g. "Cedar Ridge Interiors Pvt Ltd". The
industry nouns come from the pack; the other pools live here.
"""

import random

NATURE_WORDS = [
	"Cedar",
	"Banyan",
	"Neem",
	"Teak",
	"Lotus",
	"Jasmine",
	"Peacock",
	"Monsoon",
	"Saffron",
	"Indigo",
	"Amber",
	"Coral",
	"Ivory",
	"Emerald",
	"Silver",
	"Golden",
	"Crimson",
	"Sandal",
	"Tamarind",
	"Mango",
	"Coconut",
	"Palm",
	"Bamboo",
	"Cypress",
	"Willow",
	"Maple",
	"Orchid",
	"Marigold",
	"Hibiscus",
	"Kingfisher",
	"Falcon",
	"Sparrow",
	"Heron",
	"Tiger",
	"Elephant",
	"Sunrise",
	"Sunset",
	"Rainbow",
	"Starlight",
	"Moonlight",
	"Northwind",
	"Southern",
	"Eastern",
	"Western",
	"Bluebell",
	"Greenleaf",
	"Redwood",
	"Blackstone",
	"Whitehall",
	"Evergreen",
]

PLACE_WORDS = [
	"Ridge",
	"Valley",
	"River",
	"Harbour",
	"Hill",
	"Field",
	"Grove",
	"Bay",
	"Coast",
	"Delta",
	"Meadow",
	"Garden",
	"Lake",
	"Spring",
	"Brook",
	"Point",
	"Crest",
	"Haven",
	"Gate",
	"Bridge",
	"Stone",
	"Oak",
	"Granite",
	"Marble",
	"Copper",
	"Brass",
	"Iron",
	"Steel",
	"Timber",
	"Clay",
	"Crystal",
	"Pearl",
	"Silk",
	"Cotton",
	"Jute",
	"Cane",
	"Craft",
	"Works",
	"Line",
	"Star",
]

LEGAL_SUFFIXES = ["Pvt Ltd", "Private Limited", "LLP", "Enterprises", "& Co", "Traders", "LLC", "Inc"]


def brand(rng: random.Random) -> str:
	return f"{rng.choice(NATURE_WORDS)} {rng.choice(PLACE_WORDS)}"


def company_name(rng: random.Random, industry_nouns: list[str], suffix: str | None = None) -> str:
	return f"{brand(rng)} {rng.choice(industry_nouns)} {suffix or rng.choice(LEGAL_SUFFIXES[:3])}"


def abbreviation(name: str, taken: set[str]) -> str:
	"""Initials of the name without the legal suffix, unique among `taken` (case-insensitive)."""
	words = name
	for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
		if words.endswith(" " + suffix):
			words = words[: -len(suffix) - 1]
			break
	base = "".join(w[0] for w in words.split() if w[0].isalnum()).upper() or "DEMO"
	taken = {t.upper() for t in taken}
	abbr, n = base, 1
	while abbr in taken:
		n += 1
		abbr = f"{base}{n}"
	return abbr


# ---------------------------------------------------------------- people
# Regional pools so a Chennai customer has a Tamil name and a Kolkata one a Bengali name.
PEOPLE = {
	"tamil": (
		[
			"Arun",
			"Karthik",
			"Senthil",
			"Priya",
			"Lakshmi",
			"Meena",
			"Vignesh",
			"Divya",
			"Saravanan",
			"Kavitha",
			"Murali",
			"Anitha",
			"Ganesh",
			"Revathi",
			"Suresh",
			"Deepa",
			"Bala",
			"Nithya",
			"Ramesh",
			"Sangeetha",
		],
		[
			"Raman",
			"Subramanian",
			"Krishnan",
			"Murugan",
			"Selvam",
			"Pandian",
			"Natarajan",
			"Venkatesan",
			"Sundaram",
			"Rajendran",
			"Govindan",
			"Annamalai",
			"Chandran",
			"Shanmugam",
			"Kannan",
		],
	),
	"south": (
		[
			"Ravi",
			"Sunil",
			"Anjali",
			"Manjunath",
			"Shwetha",
			"Srinivas",
			"Lakshmi",
			"Harish",
			"Bindu",
			"Kiran",
			"Raghav",
			"Sneha",
			"Mahesh",
			"Divya",
			"Prakash",
			"Asha",
			"Naveen",
			"Rekha",
			"Vinod",
			"Sowmya",
		],
		[
			"Reddy",
			"Rao",
			"Gowda",
			"Nair",
			"Menon",
			"Shetty",
			"Hegde",
			"Pillai",
			"Naidu",
			"Kumar",
			"Varma",
			"Kurup",
			"Bhat",
			"Kamath",
			"Prasad",
		],
	),
	"west": (
		[
			"Amit",
			"Neha",
			"Rahul",
			"Pooja",
			"Sachin",
			"Kavita",
			"Nikhil",
			"Sneha",
			"Rohan",
			"Anita",
			"Vikram",
			"Shruti",
			"Hemant",
			"Rupal",
			"Jignesh",
			"Mitali",
			"Tushar",
			"Komal",
			"Parag",
			"Swati",
		],
		[
			"Patil",
			"Deshmukh",
			"Joshi",
			"Kulkarni",
			"Shah",
			"Patel",
			"Mehta",
			"Desai",
			"Pawar",
			"Jadhav",
			"Gokhale",
			"Bhatt",
			"Parikh",
			"Naik",
			"Sawant",
		],
	),
	"north": (
		[
			"Rajesh",
			"Sunita",
			"Vikas",
			"Anjali",
			"Manoj",
			"Rekha",
			"Deepak",
			"Pooja",
			"Sanjay",
			"Neetu",
			"Ajay",
			"Ritu",
			"Pankaj",
			"Shalini",
			"Gaurav",
			"Preeti",
			"Alok",
			"Nisha",
			"Rohit",
			"Kiran",
		],
		[
			"Sharma",
			"Verma",
			"Gupta",
			"Singh",
			"Agarwal",
			"Mishra",
			"Yadav",
			"Chauhan",
			"Malhotra",
			"Kapoor",
			"Saxena",
			"Tiwari",
			"Arora",
			"Bansal",
			"Srivastava",
		],
	),
	"east": (
		[
			"Sourav",
			"Ananya",
			"Debasish",
			"Rumpa",
			"Subrata",
			"Moumita",
			"Amitava",
			"Sriparna",
			"Biswajit",
			"Payel",
			"Arindam",
			"Tanushree",
			"Pradeep",
			"Smita",
			"Rakesh",
			"Jyoti",
			"Manas",
			"Sanghamitra",
			"Prasanta",
			"Rina",
		],
		[
			"Banerjee",
			"Chatterjee",
			"Mukherjee",
			"Das",
			"Ghosh",
			"Bose",
			"Sen",
			"Dutta",
			"Mohanty",
			"Patnaik",
			"Sinha",
			"Roy",
			"Saha",
			"Kar",
			"Mahapatra",
		],
	),
}

STATE_REGION = {
	"Tamil Nadu": "tamil",
	"Puducherry": "tamil",
	"Karnataka": "south",
	"Kerala": "south",
	"Andhra Pradesh": "south",
	"Telangana": "south",
	"Maharashtra": "west",
	"Gujarat": "west",
	"Goa": "west",
	"West Bengal": "east",
	"Odisha": "east",
	"Bihar": "east",
	"Jharkhand": "east",
	"Assam": "east",
	"Sikkim": "east",
	"Tripura": "east",
	"Arunachal Pradesh": "east",
	"Manipur": "east",
	"Meghalaya": "east",
	"Mizoram": "east",
	"Nagaland": "east",
	"Andaman and Nicobar Islands": "east",
	"Lakshadweep Islands": "south",
	"Dadra and Nagar Haveli and Daman and Diu": "west",
}


def person(rng: random.Random, state: str) -> tuple[str, str]:
	first, last = PEOPLE[STATE_REGION.get(state, "north")]
	return rng.choice(first), rng.choice(last)


# German umlauts are written out; other accents lose their mark (ş -> s, é -> e)
_TRANSLITERATE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "ı": "i"})


def slug(text: str) -> str:
	"""Lower-case ASCII letters and digits only (e-mail addresses, lookups)."""
	import unicodedata

	text = unicodedata.normalize("NFKD", text.lower().translate(_TRANSLITERATE))
	return "".join(ch for ch in text if ch.isascii() and ch.isalnum())


def email_for_person(rng: random.Random, first: str, last: str) -> str:
	# example.com is reserved for documentation (RFC 2606), so these never reach anyone
	return f"{slug(first)}.{slug(last)}{rng.randint(1, 99)}@example.com"


def email_for_business(name: str) -> str:
	words = name
	for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
		if words.endswith(" " + suffix):
			words = words[: -len(suffix) - 1]
			break
	return f"accounts@{slug(words)}.example.com"


def mobile(rng: random.Random) -> str:
	return f"+91-{rng.choice('6789')}{rng.randint(0, 9999):04d}-{rng.randint(0, 99999):05d}"
