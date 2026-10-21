"""
estate_functions.py — Property data + search logic for GharSetu Realty voice bot.

v4 UPGRADE: Replaced empty stubs with a structured in-memory dataset
and real filtering logic (location, budget, property_type).
Replace PROPERTY_DB with a real DB call without touching agent_graph.py.
"""

import time
import uuid
from typing import Optional


# ================================================================
# PROPERTY DATABASE (structured, filterable)
# ================================================================

PROPERTY_DB: list[dict] = [
    # --- COMMERCIAL ---
    {
        "id": "C001", "type": "commercial", "category": "commercial",
        "location": "Khandwa Road", "city": "Indore",
        "price": 50_000_000, "price_display": "paanch crore",
        "bhk": None, "area_sqft": None,
        "description": "Commercial space, Khandwa Road Indore",
    },
    {
        "id": "C002", "type": "commercial", "category": "commercial",
        "location": "Indore Ujjain State Road", "city": "Indore",
        "price": 3_600_000, "price_display": "chhattees lakh",
        "bhk": None, "area_sqft": None,
        "description": "Commercial property, Indore Ujjain State Road",
    },
    {
        "id": "C003", "type": "commercial", "category": "commercial",
        "location": "LIG Main Square", "city": "Indore",
        "price": 25_000_000, "price_display": "dhai crore",
        "bhk": None, "area_sqft": None,
        "description": "Commercial, LIG Main Square",
    },
    # --- APARTMENTS ---
    {
        "id": "A001", "type": "apartment", "category": "residential",
        "location": "Vinayak Enclave Scheme 140", "city": "Indore",
        "price": 700_000, "price_display": "saath lakh",
        "bhk": 3, "area_sqft": 1050,
        "description": "3 BHK Apartment, Scheme 140",
    },
    {
        "id": "A002", "type": "apartment", "category": "residential",
        "location": "Shriji Valley Bicholi", "city": "Indore",
        "price": 2_400_000, "price_display": "chaubees lakh",
        "bhk": 2, "area_sqft": 850,
        "description": "Apartment, Bicholi Mardana",
    },
    {
        "id": "A003", "type": "apartment", "category": "residential",
        "location": "MR-11 Ring Road", "city": "Indore",
        "price": 12_000_000, "price_display": "ek crore bees lakh",
        "bhk": 4, "area_sqft": 2200,
        "description": "4 BHK Luxury Apartment, Ring Road",
    },
    # --- HOUSES ---
    {
        "id": "H001", "type": "house", "category": "residential",
        "location": "Navda Panth", "city": "Indore",
        "price": 3_200_000, "price_display": "battees lakh",
        "bhk": 3, "area_sqft": 1200,
        "description": "Row House, Navda Panth",
    },
    {
        "id": "H002", "type": "house", "category": "residential",
        "location": "Omaxe City Bypass", "city": "Indore",
        "price": 4_000_000, "price_display": "chaalees lakh",
        "bhk": 4, "area_sqft": 1800,
        "description": "House, Omaxe City Bypass Indore",
    },
    {
        "id": "H003", "type": "house", "category": "residential",
        "location": "Kanadia Bypass", "city": "Indore",
        "price": 14_000_000, "price_display": "ek crore chaalees lakh",
        "bhk": 4, "area_sqft": 2400,
        "description": "House, Kanadia Bypass",
    },
    {
        "id": "H004", "type": "house", "category": "residential",
        "location": "Kalindi Gold", "city": "Indore",
        "price": 4_000_000, "price_display": "chaalees lakh",
        "bhk": 3, "area_sqft": 1400,
        "description": "House, Kalindi Gold Indore",
    },
    # --- PLOTS ---
    {
        "id": "P001", "type": "plot", "category": "plot",
        "location": "Super Corridor near TCS Puwarda", "city": "Indore",
        "price_per_sqft": 4500, "price_display": "char hazar paanch sau per sqft",
        "price": None, "bhk": None, "area_sqft": None,
        "description": "Plot, Super Corridor near TCS Infosys",
    },
    {
        "id": "P002", "type": "plot", "category": "plot",
        "location": "Bypass Omaxe Pratham", "city": "Indore",
        "price_per_sqft": 6000, "price_display": "chhe hazar per sqft",
        "price": None, "bhk": None, "area_sqft": None,
        "description": "Plot, Bypass Indore Omaxe Pratham",
    },
    {
        "id": "P003", "type": "plot", "category": "plot",
        "location": "Indore Ujjain Road", "city": "Indore",
        "price_per_sqft": 3800, "price_display": "teen hazar aath sau per sqft",
        "price": None, "bhk": None, "area_sqft": None,
        "description": "Plot, Indore Ujjain Road near toll Naka",
    },
    {
        "id": "P004", "type": "plot", "category": "plot",
        "location": "Medical Hub Super Corridor", "city": "Indore",
        "price_per_sqft": 8500, "price_display": "aath hazar paanch sau per sqft",
        "price": None, "bhk": None, "area_sqft": None,
        "description": "Plot, Medical Hub near Yes Technology Super Corridor",
    },
    # --- NEW PROPERTIES (Indore expansion) ---
    {
        "id": "A004", "type": "apartment", "category": "residential",
        "location": "Vijay Nagar AB Road", "city": "Indore",
        "price": 5_500_000, "price_display": "pachpan lakh",
        "bhk": 3, "area_sqft": 1350,
        "description": "3 BHK Apartment, Vijay Nagar AB Road Indore",
    },
    {
        "id": "A005", "type": "apartment", "category": "residential",
        "location": "Nipania Main Road", "city": "Indore",
        "price": 3_800_000, "price_display": "aththees lakh",
        "bhk": 2, "area_sqft": 950,
        "description": "2 BHK Apartment, Nipania Main Road Indore",
    },
    {
        "id": "A006", "type": "apartment", "category": "residential",
        "location": "Scheme 54 Vijay Nagar", "city": "Indore",
        "price": 7_200_000, "price_display": "bahattar lakh",
        "bhk": 3, "area_sqft": 1650,
        "description": "3 BHK Apartment, Scheme 54 near Vijay Nagar",
    },
    {
        "id": "H005", "type": "house", "category": "residential",
        "location": "Paliya Naka Rajendra Nagar", "city": "Indore",
        "price": 5_200_000, "price_display": "baavan lakh",
        "bhk": 3, "area_sqft": 1600,
        "description": "House, Paliya Naka Rajendra Nagar Indore",
    },
    {
        "id": "H006", "type": "house", "category": "residential",
        "location": "Mahalakshmi Nagar Indore", "city": "Indore",
        "price": 8_500_000, "price_display": "pachasi lakh",
        "bhk": 4, "area_sqft": 2100,
        "description": "4 BHK Independent House, Mahalakshmi Nagar",
    },
    {
        "id": "H007", "type": "house", "category": "residential",
        "location": "Tilak Nagar AB Road", "city": "Indore",
        "price": 6_000_000, "price_display": "saath lakh",
        "bhk": 3, "area_sqft": 1700,
        "description": "Row House, Tilak Nagar AB Road Indore",
    },
    {
        "id": "C004", "type": "commercial", "category": "commercial",
        "location": "Palasia Chowk Indore", "city": "Indore",
        "price": 18_000_000, "price_display": "ek crore assi lakh",
        "bhk": None, "area_sqft": 800,
        "description": "Commercial Office Space, Palasia Chowk Indore",
    },
    {
        "id": "C005", "type": "commercial", "category": "commercial",
        "location": "Bhawarkuan Main Road", "city": "Indore",
        "price": 9_000_000, "price_display": "nabbe lakh",
        "bhk": None, "area_sqft": 500,
        "description": "Showroom cum Office, Bhawarkuan Main Road",
    },
    {
        "id": "P005", "type": "plot", "category": "plot",
        "location": "Rau Pithampur Road", "city": "Indore",
        "price_per_sqft": 2800, "price_display": "do hazar aath sau per sqft",
        "price": None, "bhk": None, "area_sqft": None,
        "description": "Residential Plot, Rau Pithampur Road Indore",
    },
    {
        "id": "P006", "type": "plot", "category": "plot",
        "location": "Lasudia Mori Scheme 78", "city": "Indore",
        "price_per_sqft": 5200, "price_display": "paanch hazar do sau per sqft",
        "price": None, "bhk": None, "area_sqft": None,
        "description": "NA Plot, Lasudia Mori Scheme 78 Indore",
    },
    {
        "id": "A007", "type": "apartment", "category": "residential",
        "location": "Annapurna Road Indore", "city": "Indore",
        "price": 2_800_000, "price_display": "aththaais lakh",
        "bhk": 2, "area_sqft": 880,
        "description": "2 BHK Apartment, Annapurna Road Indore",
    },
    # --- SUPER CORRIDOR RESIDENTIAL (new) ---
    {
        "id": "A008", "type": "apartment", "category": "residential",
        "location": "Super Corridor Puwarda Indore", "city": "Indore",
        "price": 4_500_000, "price_display": "paytaalees lakh",
        "bhk": 2, "area_sqft": 1000,
        "description": "2 BHK Apartment, Super Corridor near TCS Infosys",
    },
    {
        "id": "A009", "type": "apartment", "category": "residential",
        "location": "Super Corridor IIM Road Indore", "city": "Indore",
        "price": 6_500_000, "price_display": "painsath lakh",
        "bhk": 3, "area_sqft": 1400,
        "description": "3 BHK Apartment, Super Corridor IIM Road Indore",
    },
    {
        "id": "A010", "type": "apartment", "category": "residential",
        "location": "Super Corridor Omaxe Indore", "city": "Indore",
        "price": 8_500_000, "price_display": "pachasi lakh",
        "bhk": 3, "area_sqft": 1700,
        "description": "3 BHK Premium Flat, Super Corridor Omaxe Township",
    },
    # --- BIJALPUR RESIDENTIAL (new) ---
    {
        "id": "A011", "type": "apartment", "category": "residential",
        "location": "Bijalpur Main Road Indore", "city": "Indore",
        "price": 3_200_000, "price_display": "battees lakh",
        "bhk": 2, "area_sqft": 900,
        "description": "2 BHK Apartment, Bijalpur Main Road Indore",
    },
    {
        "id": "H008", "type": "house", "category": "residential",
        "location": "Bijalpur Colony Indore", "city": "Indore",
        "price": 4_800_000, "price_display": "aadthaalees lakh",
        "bhk": 3, "area_sqft": 1500,
        "description": "3 BHK Independent House, Bijalpur Colony Indore",
    },
    # --- BHAWARKUAN RESIDENTIAL (new) ---
    {
        "id": "A012", "type": "apartment", "category": "residential",
        "location": "Bhawarkuan Main Road Indore", "city": "Indore",
        "price": 4_200_000, "price_display": "baayalees lakh",
        "bhk": 2, "area_sqft": 950,
        "description": "2 BHK Apartment, Bhawarkuan Main Road Indore",
    },
    {
        "id": "A013", "type": "apartment", "category": "residential",
        "location": "Bhawarkuan Square Indore", "city": "Indore",
        "price": 5_800_000, "price_display": "aththaavan lakh",
        "bhk": 3, "area_sqft": 1350,
        "description": "3 BHK Apartment, Bhawarkuan Square Indore",
    },
    # --- SUKHLIYA / TEJAJI NAGAR (new) ---
    {
        "id": "A014", "type": "apartment", "category": "residential",
        "location": "Sukhliya Indore", "city": "Indore",
        "price": 4_000_000, "price_display": "chaalees lakh",
        "bhk": 2, "area_sqft": 900,
        "description": "2 BHK Apartment, Sukhliya Indore",
    },
    {
        "id": "A015", "type": "apartment", "category": "residential",
        "location": "Tejaji Nagar Indore", "city": "Indore",
        "price": 3_500_000, "price_display": "paaintees lakh",
        "bhk": 2, "area_sqft": 870,
        "description": "2 BHK Apartment, Tejaji Nagar Indore",
    },
    # --- KANADIYA ROAD / MR-9 (new) ---
    {
        "id": "A016", "type": "apartment", "category": "residential",
        "location": "Kanadiya Road Indore", "city": "Indore",
        "price": 4_600_000, "price_display": "chhiyaalees lakh",
        "bhk": 3, "area_sqft": 1200,
        "description": "3 BHK Apartment, Kanadiya Road Indore",
    },
    # --- KHAJRANA / BANGANGA (new) ---
    {
        "id": "A017", "type": "apartment", "category": "residential",
        "location": "Khajrana Indore", "city": "Indore",
        "price": 3_000_000, "price_display": "tees lakh",
        "bhk": 2, "area_sqft": 820,
        "description": "2 BHK Apartment, Khajrana Indore",
    },
    # --- SCHEME 78 RESIDENTIAL (new) ---
    {
        "id": "H009", "type": "house", "category": "residential",
        "location": "Scheme 78 Vijay Nagar Indore", "city": "Indore",
        "price": 9_500_000, "price_display": "panchanabbe lakh",
        "bhk": 4, "area_sqft": 2200,
        "description": "4 BHK Independent House, Scheme 78 Vijay Nagar Indore",
    },
    # --- AIRPORT ROAD / AERODROME (new) ---
    {
        "id": "A018", "type": "apartment", "category": "residential",
        "location": "Aerodrome Road Indore", "city": "Indore",
        "price": 7_500_000, "price_display": "pachhattar lakh",
        "bhk": 3, "area_sqft": 1550,
        "description": "3 BHK Apartment, Aerodrome Road Indore",
    },
    # --- MANGALIYA / LIMBODI (new) ---
    {
        "id": "P007", "type": "plot", "category": "plot",
        "location": "Mangaliya Sadak Indore", "city": "Indore",
        "price_per_sqft": 2200, "price_display": "do hazar do sau per sqft",
        "price": None, "bhk": None, "area_sqft": None,
        "description": "Residential Plot, Mangaliya Sadak Indore",
    },
    # --- SAKET NAGAR / AB ROAD (new) ---
    {
        "id": "A019", "type": "apartment", "category": "residential",
        "location": "Saket Nagar AB Road Indore", "city": "Indore",
        "price": 6_800_000, "price_display": "aththasath lakh",
        "bhk": 3, "area_sqft": 1480,
        "description": "3 BHK Apartment, Saket Nagar AB Road Indore",
    },
]

# Location keyword → partial match list
_LOCATION_ALIASES: dict[str, list[str]] = {
    "super corridor": ["super corridor", "puwarda", "tcs", "infosys", "medical hub"],
    "khandwa road": ["khandwa", "khandwa road"],
    "bypass": ["bypass", "omaxe", "kanadia bypass"],
    "vijay nagar": ["vijay nagar", "vijay", "ab road", "scheme 54"],
    "scheme 140": ["scheme 140", "scheme140", "vinayak"],
    "nipania": ["nipania", "nipania main"],
    "bicholi": ["bicholi", "bicholi mardana"],
    "ring road": ["ring road", "mr-11", "mr 11"],
    "ujjain road": ["ujjain road", "ujjain state road", "magarkheda", "ringnodiya"],
    "rajendra nagar": ["rajendra nagar", "paliya", "paliya naka"],
    "mahalakshmi nagar": ["mahalakshmi", "mahalakshmi nagar"],
    "tilak nagar": ["tilak nagar", "tilak"],
    "palasia": ["palasia", "palasia chowk"],
    "bhawarkuan": ["bhawarkuan", "bhawar kuan"],
    "rau": ["rau", "pithampur", "rau pithampur"],
    "lasudia": ["lasudia", "scheme 78", "lasudia mori"],
    "annapurna": ["annapurna", "annapurna road"],
    "bijalpur": ["bijalpur", "beejalpur"],
    "bhawarkuan": ["bhawarkuan", "bhawar kuan", "bhawarkua", "bhanwarkua"],
    "sukhliya": ["sukhliya", "sukhliya nagar"],
    "tejaji nagar": ["tejaji", "tejaji nagar"],
    "kanadiya": ["kanadiya", "kanadiya road", "kanadia road", "mr-9"],
    "khajrana": ["khajrana", "banganga"],
    "scheme 78": ["scheme 78", "scheme78"],
    "aerodrome": ["aerodrome", "airport road", "aerodrome road"],
    "mangaliya": ["mangaliya", "mangalia", "limbodi"],
    "saket nagar": ["saket", "saket nagar"],
    "indore": ["indore"],  # catch-all for city
}


def _location_matches(prop_location: str, query_location: str) -> bool:
    """Fuzzy location match — checks aliases."""
    pl = prop_location.lower()
    ql = query_location.lower()
    if ql in pl or pl in ql:
        return True
    for _key, aliases in _LOCATION_ALIASES.items():
        if any(a in ql for a in aliases):
            if any(a in pl for a in aliases):
                return True
    return False


def _budget_matches(prop: dict, min_b: Optional[int], max_b: Optional[int]) -> bool:
    """Check if property price falls within budget range."""
    if min_b is None and max_b is None:
        return True
    price = prop.get("price")
    if price is None:
        return True  # plots with per-sqft pricing — always include
    margin = 0.25  # allow 25% over budget (common in voice calls)
    if max_b is not None and price > max_b * (1 + margin):
        return False
    if min_b is not None and price < min_b * 0.5:
        return False
    return True


def _type_matches(prop: dict, property_type: str) -> bool:
    """Check if property type matches query."""
    if not property_type:
        return True
    pt = property_type.lower()
    cat = prop.get("category", "")
    typ = prop.get("type", "")
    if "commercial" in pt:
        return cat == "commercial"
    if any(w in pt for w in ("plot", "land", "zameen")):
        return cat == "plot"
    if any(w in pt for w in ("flat", "apartment", "residential")):
        return cat == "residential" and typ in ("apartment", "house")
    import re
    # BHK range: "2-3 BHK", "2 se 3 BHK", "do teen BHK", "2 ya 3 BHK"
    range_match = re.search(r"(\d)\s*[-–seya]+\s*(\d)\s*bhk", pt)
    if range_match:
        lo, hi = int(range_match.group(1)), int(range_match.group(2))
        prop_bhk = prop.get("bhk")
        if prop_bhk is None:
            return False
        return lo <= prop_bhk <= hi

    # Single BHK
    bhk_match = None
    m = re.search(r"(\d)\s*bhk", pt)
    if m:
        bhk_match = int(m.group(1))
    if bhk_match is not None:
        return prop.get("bhk") == bhk_match
    return True


# ================================================================
# PUBLIC API — called by tool functions
# ================================================================

def search_property(
    purpose: str,
    location: str,
    property_type: str = "",
    budget: str = "",
    budget_structured: dict = None,
) -> dict:
    """
    Filter PROPERTY_DB and return matching listings.
    budget_structured: {min_budget: int, max_budget: int} if available.
    """
    min_b = max_b = None
    if budget_structured:
        min_b = budget_structured.get("min_budget")
        max_b = budget_structured.get("max_budget")
    elif budget:
        # Fallback: crude parse from string
        import re
        nums = re.findall(r"\d+(?:\.\d+)?", budget)
        if nums:
            unit = 100_000 if "lakh" in budget.lower() else (
                10_000_000 if "crore" in budget.lower() else 1
            )
            if len(nums) == 2:
                min_b = int(float(nums[0]) * unit)
                max_b = int(float(nums[1]) * unit)
            else:
                min_b = max_b = int(float(nums[0]) * unit)

    results = [
        p for p in PROPERTY_DB
        if _location_matches(p["location"], location)
        and _type_matches(p, property_type)
        and _budget_matches(p, min_b, max_b)
    ]

    if not results:
        # Try with relaxed budget — 20% above max
        relaxed_results = []
        if max_b:
            relaxed_max = int(max_b * 1.25)
            relaxed_results = [
                p for p in PROPERTY_DB
                if _location_matches(p["location"], location)
                and _type_matches(p, property_type)
                and _budget_matches(p, min_b, relaxed_max)
            ]

        if relaxed_results:
            suggestion = relaxed_results[0]
            price_disp = suggestion.get("price_display", "")
            return {
                "message": (
                    f"Abhi {location} mein is budget mein koi property available nahi hai. "
                    f"Lekin agar thoda budget badhayein toh ek option hai — "
                    f"{suggestion['description']} {price_disp}. "
                    f"Aapki requirement note kar li hai, jaise hi koi naya option aaye, "
                    f"main aapko turant bataungi."
                ),
                "count": 0,
                "listings": [],
                "suggestion": suggestion,
            }

        return {
            "message": (
                f"Abhi {location} mein aapke budget mein koi matching property nahi hai. "
                f"Budget thoda badhayein ya koi aur area try karein — "
                f"Nipania, Vijay Nagar, ya Scheme 140 mein options hain. "
                f"Main aapki requirement note kar rahi hoon, jaise hi koi sahi property aaye "
                f"main khud call karungi."
            ),
            "count": 0,
            "listings": [],
        }

    # Format for voice response — max 4 listings, natural spoken style per property
    spoken_parts = []
    for p in results[:4]:
        loc = p["location"].split(" Indore")[0].split(" Puwarda")[0]
        price = p.get("price_display", "")
        bhk = p.get("bhk")
        ptype = p.get("type", "")
        area = p.get("area_sqft")

        if ptype == "plot" or p.get("category") == "plot":
            per_sqft = p.get("price_per_sqft", "")
            spoken_parts.append(
                f"{loc} mein ek plot hai — {price},"
                + (f" {area} sqft ka" if area else "")
            )
        else:
            bhk_str = f"{bhk} BHK " if bhk else ""
            area_str = f", {area} sqft" if area else ""
            spoken_parts.append(
                f"{loc} mein {bhk_str}{ptype} — {price}{area_str}"
            )

    count_word = len(results)
    intro = (
        f"Hamare paas {location} mein {count_word} verified options hain —"
        if count_word > 1
        else f"{location} mein ek achha option hai —"
    )
    message = (
        intro + " " + "; ".join(spoken_parts) + ". "
        "Koi bhi option pasand aaye toh bataiye, main visit arrange kar sakti hoon."
    )

    return {"message": message, "count": len(results), "listings": results[:4]}


def get_property_details(property_id: str) -> dict:
    for p in PROPERTY_DB:
        if p["id"] == property_id:
            return {
                "property_id": property_id,
                "description": p["description"],
                "price_display": p.get("price_display", ""),
                "location": p["location"],
                "bhk": p.get("bhk"),
                "area_sqft": p.get("area_sqft"),
                "type": p["type"],
            }
    return {"error": f"Property '{property_id}' details abhi available nahi hain."}


def schedule_visit(
    customer_name: str, property_id: str, visit_date: str
) -> dict:
    visit_id = f"V{int(time.time())}"
    return {
        "visit_id": visit_id,
        "message": (
            f"Visit note kar li hai {visit_date} ke liye. "
            "Hamare team member confirm karenge."
        ),
        "property_id": property_id,
    }


def lookup_visit(visit_id: str) -> dict:
    return {
        "message": f"Visit {visit_id} ka status hamare team se confirm hoga."
    }


def post_property(
    owner_name: str, property_type: str, location: str, price: str
) -> dict:
    return {
        "property_id": f"prop_{uuid.uuid4().hex[:8]}",
        "message": (
            f"{owner_name} ji, property detail note kar li. "
            "Team jald contact karegi."
        ),
    }


def save_confirmed_customer(
    phone: str,
    name: str,
    intent: str,
    location: str,
    budget: str,
    property_type: str = "",
    visit_scheduled: bool = False,
    visit_date: str = "",
    notes: str = "",
) -> dict:
    """
    Save a fully confirmed/deal-done customer to customer_memory.json.
    Marks stage as 'confirmed' and logs timestamp.
    Called when all info is collected OR a visit is scheduled.
    """
    import json as _json
    from pathlib import Path as _Path

    MEMORY_FILE = _Path(__file__).parent / "customer_memory.json"

    def _load():
        if MEMORY_FILE.exists():
            try:
                return _json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(data):
        MEMORY_FILE.write_text(
            _json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    mem = _load()
    existing = mem.get(phone, {})

    confirmed_entry = {
        **existing,
        "name": name or existing.get("name", ""),
        "intent": intent or existing.get("intent", ""),
        "preferred_location": location or existing.get("preferred_location", ""),
        "budget": budget or existing.get("budget", ""),
        "property_type": property_type or existing.get("property_type", ""),
        "stage": "confirmed",
        "confirmed_at": time.strftime("%Y-%m-%d %H:%M"),
        "last_called": time.strftime("%Y-%m-%d"),
    }
    if visit_scheduled:
        confirmed_entry["visit_scheduled"] = True
        confirmed_entry["visit_date"] = visit_date
    if notes:
        confirmed_entry["notes"] = notes

    mem[phone] = confirmed_entry
    _save(mem)

    return {
        "status": "confirmed",
        "message": (
            f"{name} ji ka profile confirm ho gaya. "
            "Team member jald follow-up karenge."
        ),
        "profile": confirmed_entry,
    }


FUNCTION_MAP = {
    "search_property":        search_property,
    "get_property_details":   get_property_details,
    "schedule_visit":         schedule_visit,
    "lookup_visit":           lookup_visit,
    "post_property":          post_property,
    "save_confirmed_customer": save_confirmed_customer,
}