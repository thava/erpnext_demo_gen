"""Curated cities with state and a real 3-digit pincode prefix.

india_compliance validates that an address pincode falls inside its state's
range (STATE_PINCODE_MAPPING), so each city carries a prefix from that range;
tests/test_india.py checks every entry. State names match india_compliance's
STATE_NUMBERS keys.
"""

import random

# state -> [(city, pincode prefix)]
CITIES = {
	"Tamil Nadu": [
		("Chennai", 600),
		("Coimbatore", 641),
		("Madurai", 625),
		("Tiruchirappalli", 620),
		("Salem", 636),
		("Tirunelveli", 627),
		("Erode", 638),
		("Vellore", 632),
	],
	"Karnataka": [
		("Bengaluru", 560),
		("Mysuru", 570),
		("Mangaluru", 575),
		("Hubballi", 580),
		("Belagavi", 590),
	],
	"Kerala": [("Kochi", 682), ("Thiruvananthapuram", 695), ("Kozhikode", 673), ("Thrissur", 680)],
	"Andhra Pradesh": [("Visakhapatnam", 530), ("Vijayawada", 520), ("Guntur", 522), ("Tirupati", 517)],
	"Telangana": [("Hyderabad", 500), ("Warangal", 506), ("Karimnagar", 505)],
	"Puducherry": [("Puducherry", 605)],
	"Maharashtra": [("Mumbai", 400), ("Pune", 411), ("Nagpur", 440), ("Nashik", 422), ("Aurangabad", 431)],
	"Gujarat": [("Ahmedabad", 380), ("Surat", 395), ("Vadodara", 390), ("Rajkot", 360)],
	"Goa": [("Panaji", 403)],
	"Delhi": [("New Delhi", 110)],
	"Haryana": [("Gurugram", 122), ("Faridabad", 121)],
	"Uttar Pradesh": [("Lucknow", 226), ("Noida", 201), ("Kanpur", 208), ("Varanasi", 221)],
	"Rajasthan": [("Jaipur", 302), ("Jodhpur", 342), ("Udaipur", 313)],
	"Punjab": [("Ludhiana", 141), ("Amritsar", 143)],
	"Chandigarh": [("Chandigarh", 160)],
	"Uttarakhand": [("Dehradun", 248)],
	"Madhya Pradesh": [("Indore", 452), ("Bhopal", 462)],
	"Chhattisgarh": [("Raipur", 492)],
	"West Bengal": [("Kolkata", 700), ("Siliguri", 734)],
	"Odisha": [("Bhubaneswar", 751), ("Cuttack", 753)],
	"Bihar": [("Patna", 800)],
	"Jharkhand": [("Ranchi", 834), ("Jamshedpur", 831)],
	"Assam": [("Guwahati", 781)],
}

STREETS = [
	"Anna Salai",
	"MG Road",
	"Station Road",
	"Gandhi Nagar",
	"Nehru Street",
	"Market Road",
	"Industrial Estate",
	"Ring Road",
	"Temple Street",
	"Lake View Road",
	"Church Street",
	"Bazaar Street",
	"Main Road",
	"Cross Street",
	"Park Avenue",
	"Mill Road",
]


def state_code(state: str) -> str:
	from india_compliance.gst_india.constants import STATE_NUMBERS

	return STATE_NUMBERS[state]


def make_address(rng: random.Random, state: str) -> dict:
	"""Address fields (line 1, city, state, pincode) for a random city in the state."""
	city, prefix = rng.choice(CITIES[state])
	return {
		"address_line1": f"{rng.randint(1, 250)}, {rng.choice(STREETS)}",
		"city": city,
		"state": state,
		"pincode": f"{prefix}{rng.randint(1, 99):03d}",
		"country": "India",
	}
