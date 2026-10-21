"""
agent_graph.py — Groq brain for GharSetu Realty Real Estate voice bot.

PRODUCTION v4 — KEY CHANGES:
  1. CLEAN LLM-DRIVEN FLOW — hardcoded step bypasses removed. LLM guided
     entirely by structured memory context injected into system prompt.
  2. STREAMING STABILITY — improved sentence splitter that never splits
     mid-Devanagari-word. Buffer only flushes on real punctuation or safe length.
  3. INTENT DETECTION — lightweight pre-LLM classifier handles greetings,
     name responses, and obvious intents instantly (zero LLM latency).
  4. BUDGET PARSER — comprehensive Hindi/Hinglish/numeric range parser
     produces structured {min_budget, max_budget, display} dict.
  5. STRUCTURED MEMORY — replaces flat dict with typed ConversationState.
  6. LATENCY — max_tokens=120, temperature=0.2, no duplicate LLM calls.
  7. NO TIMEOUT CRASH — chat_stream never raises TimeoutError; generator
     ends cleanly and main.py handles the None sentinel gracefully.
"""

import asyncio
import json
import os
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langchain_groq import ChatGroq

load_dotenv(dotenv_path=Path(__file__).parent / "_env")
load_dotenv(dotenv_path=Path(__file__).parent / ".env")


# ================================================================
# STRUCTURED MEMORY
# ================================================================

MEMORY_FILE = Path(__file__).parent / "customer_memory.json"

_NAME_BLOCKLIST = {
    # Greetings / acknowledgements — all case variants handled by .lower() check
    "hello", "hi", "haan", "han", "haan.", "haan!", "han.", "han!",
    "yes", "yeah", "yep", "yup", "sure", "no", "nahi", "nope", "nahi.",
    "haa", "ha", "hanji", "haanji", "ji", "hnji",
    "okay", "ok", "ok.", "okay.", "theek", "theek hai", "theek he",
    "accha", "achha", "acha", "aacha",
    "sahi", "bilkul", "zaroor", "zarur",
    "kaun", "kon", "bol", "bolo", "suno", "sun", "kya", "kyun",
    "huh", "hmm", "hm", "hnn", "hn", "uh", "um", "arre", "arey",
    "main", "mein", "aap", "hum", "tum",
    "hello.", "hello!", "hello?", "hi.", "hi!",
    "hello hello", "123", "1234", "12345",
    "repeat", "karo", "batao", "boliye", "bolna", "bolraha", "bolrahe",
    "collipe", "namaste", "namaskar",
    # Filler / connector words
    "aur", "ya", "toh", "par", "se", "mera", "meri", "mere", "apna",
    "woh", "voh", "yeh", "ye", "yahan", "wahan",
    # Intent / property words
    "commercial", "residential", "property", "flat", "plot", "apartment",
    "buy", "sell", "rent", "bechna", "kharidna", "khareedna", "kiraya",
    "bhk", "budget", "lakh", "crore", "rupaye", "rupee",
    # Hindi script equivalents
    "क्या", "आप", "हाँ", "हां", "हाँ।", "हां।",
    "नहीं", "नही", "मैं", "मे", "मेरा", "नमस्ते",
    "ठीक", "बोलो", "सुनो", "कौन", "ओके", "अरे",
    "हम", "वो", "यह", "यहां", "हाँजी", "हांजी", "जी",
    "अच्छा", "सही", "बिल्कुल", "ज़रूर",
}

_LOCATION_WORDS = {
    # Major MP cities
    "indore", "bhopal", "ujjain", "dewas", "ratlam", "jabalpur", "gwalior",
    "sagar", "satna", "rewa", "mandsaur", "neemuch", "shajapur", "agar",
    "khargone", "barwani", "dhar", "jhabua", "alirajpur", "betul", "hoshangabad",
    "narmadapuram", "sehore", "raisen", "vidisha", "narsinghpur", "chhindwara",
    "seoni", "balaghat", "mandla", "dindori", "anuppur", "shahdol", "umaria",
    "katni", "panna", "chhatarpur", "tikamgarh", "siwni", "damoh", "ashok",
    "nagar", "morena", "bhind", "sheopur", "datia", "shivpuri", "guna",
    "ashoknagar", "rajgarh", "agar", "malwa",
    # Indore specific areas
    "super", "corridor", "bypass", "road", "vihar", "colony",
    "scheme", "sector", "phase", "area", "location", "khandwa", "vijay",
    "nipania", "kanadia", "magarkheda", "puwarda", "ringnodiya", "paliya",
    "bajrang", "prestige", "omaxe", "kalindi", "bicholi", "lig", "ring",
    "highway", "market", "chowk", "square",
    "bhawarkuan", "bhawarkua", "bhanwarkua", "rau", "annapurna", "palasia",
    "rajendra", "mahalakshmi", "tilak", "lasudia", "navda",
    "mhow", "pithampur", "hatod", "sanwer", "aerodrome", "airport", "iim",
    "khajrana", "sudama", "nagar", "banganga", "saket", "sai", "kripa",
    "treasure", "town", "silicon", "city", "heights", "residency",
    "abhay", "prashal", "manorama", "ganga", "yamuna", "saraswati",
    "AB", "mg", "geeta", "bhawan", "gumasta", "dhanwantri",
    "geeta", "skheme", "skhema", "sukhliya", "kanadiya", "tejaji",
    "mangaliya", "mangalia", "limbodi", "depalpur", "sanwer", "mhow",
    "mundla", "nayta", "lasudiya", "bijalpur", "khudel", "simrol",
    # Bhopal specific
    "mp", "nagar", "hoshangabad", "berasia", "raisen", "sehore",
    "kolar", "mandideep", "obaidullaganj", "phanda", "misrod",
    "arera", "habibganj", "karond", "bairagarh", "bhanpur",
    "shahpura", "ayodhya", "vidya", "vihar", "trilanga",
    # Generic
    "flat", "apartment", "bhk", "commercial", "residential", "plot",
    "land", "rent", "buy", "sell", "kharidna", "bechna", "kiraya",
}


_BUDGET_WORDS_IN_NAME = re.compile(
    r"\b(lakh|lac|crore|cr|hazar|thousand|budget|rupaye|rupee)\b"
    r"|लाख|करोड़|हज़ार|हजार|रुपये|बजट"
    r"|\b(nabbe|pachaas|tees|chaalees|sattar|assi|bees|pachees)\b",
    re.IGNORECASE,
)


def _is_valid_name(text: str) -> bool:
    if not text or len(text.strip()) < 2:
        return False
    # Reject if text contains a comma — names don't have commas
    if "," in text:
        return False
    words = text.strip().split()
    if len(words) > 3:
        return False
    # Reject if the text looks like a budget amount
    if _BUDGET_WORDS_IN_NAME.search(text):
        return False
    # Reject Devanagari number words used as name
    for dnum in _DEVANAGARI_NUM_MAP:
        if dnum in text:
            return False
    # Reject if any word contains non-Indian, non-Latin characters (e.g. ã, ó, ç — foreign ASR noise)
    for w in words:
        for ch in w:
            cp = ord(ch)
            # Allow: ASCII letters (0-127), Devanagari (0900-097F), common diacritics used in Indian names
            # Reject: Latin Extended with tildes/cedillas/etc. that indicate foreign speech noise
            if ch.isalpha() and cp > 127 and not (0x0900 <= cp <= 0x097F):
                return False
    # Check each word against blocklist
    for w in words:
        if w.lower() in _NAME_BLOCKLIST or w in _NAME_BLOCKLIST:
            return False
        if w.lower() in _LOCATION_WORDS:
            return False
    if any(c.isdigit() for c in text):
        return False
    # Reject if the full text is in blocklist
    if text.strip().lower() in _NAME_BLOCKLIST or text.strip() in _NAME_BLOCKLIST:
        return False
    return True


def _load_memory() -> dict:
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_memory(data: dict):
    MEMORY_FILE.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def get_customer_profile(phone: str) -> dict:
    return _load_memory().get(phone, {})


def save_customer_profile(phone: str, profile: dict):
    mem = _load_memory()
    existing = mem.get(phone, {})
    for key, value in profile.items():
        if key == "past_visits":
            old = existing.get("past_visits", [])
            new = value if isinstance(value, list) else [value]
            existing["past_visits"] = old + [v for v in new if v not in old]
        elif value:
            existing[key] = value
    mem[phone] = existing
    _save_memory(mem)


def build_memory_context(phone: str) -> str:
    """
    Build structured context block injected into every system prompt.
    Tells LLM exactly what we know and what to ask next — no guesswork.
    """
    profile = get_customer_profile(phone)
    if not profile:
        return ""
    lines = []
    if profile.get("name"):
        lines.append(f"Customer ka naam: {profile['name']}")
    if profile.get("intent"):
        lines.append(f"Intent (kharidna/bechna/rent): {profile['intent']}")
    if profile.get("preferred_location"):
        lines.append(f"Pasandeeda location: {profile['preferred_location']}")
    if profile.get("budget"):
        b = profile["budget"]
        if isinstance(b, dict):
            display = b.get("display", "")
        else:
            display = str(b)
        lines.append(f"Budget: {display}")
    if profile.get("property_type"):
        lines.append(f"Property type: {profile['property_type']}")
    if profile.get("stage"):
        lines.append(f"Conversation stage: {profile['stage']}")
    if profile.get("confirmed_at"):
        lines.append(f"Confirmed at: {profile['confirmed_at']}")
    if profile.get("past_visits"):
        visits = ", ".join(str(v) for v in profile["past_visits"][-3:])
        lines.append(f"Pehle se scheduled visits: {visits}")

    if not lines:
        return ""

    # Determine next step — inject as explicit instruction
    p = profile
    loc = p.get("preferred_location", "")
    multi_loc = "," in loc  # user mentioned multiple locations

    if p.get("stage") == "confirmed":
        confirmed_at = p.get("confirmed_at", "")
        next_step = (
            f"CUSTOMER CONFIRMED HAI ({confirmed_at}). "
            "Deal ho gayi hai. Warmly close karo — "
            "\"Bahut achha [naam] ji! Aapki details note ho gayi hain. "
            "Hamare senior property expert aapko jald contact karenge — "
            "visit aur aage ki jaankari ke liye. "
            "Aapka bohot shukriya. GharSetu Realty mein aapka swagat hai.\" "
            "Koi naya sawaal ya upsell NAHI."
        )
    elif not p.get("intent"):
        next_step = 'NEXT STEP: Poochho — "Aap property kharidna chahte hain, bechna chahte hain, ya rent par lena chahte hain?"'
    elif not p.get("preferred_location"):
        next_step = (
            'NEXT STEP: Warmly poochho — ek friendly real estate exec ki tarah, '
            '"Aap kis area mein dekhna chahenge — Vijay Nagar, Super Corridor, Nipania, '
            'ya koi aur jagah? Hamare paas in sab areas mein verified options hain."'
        )
    elif not p.get("budget"):
        next_step = ('NEXT STEP: Dost ki tarah poochho — "Budget ka ek rough idea dijiye — approximately bhi chalega." '
                    'Agar customer bole "fix nahi" ya "decide nahi" ya "fixed nahi" — '
                    'TURANT bolo: "Samajh gayi [naam] ji, koi issue nahi — main range ke hisaab se best options suggest kar deti hoon." '
                    'Phir SEEDHA property type poochho: "Residential flat chahiye ya commercial? Aur kitne BHK?" '
                    'Budget ke baare mein DOBARA BILKUL MAT POOCHHO.')
    elif p.get("budget") and isinstance(p.get("budget"), dict) and p["budget"].get("display") == "flexible" and not p.get("property_type"):
        next_step = ('NEXT STEP: Budget flexible hai — iske baare mein DOBARA MAT POOCHHO. '
                    'Seedha poochho: "Residential flat chahiye ya commercial? Aur kitne BHK prefer karenge?"')
    elif not p.get("property_type"):
        next_step = 'NEXT STEP: Poochho — "Residential chahiye ya commercial? Aur kitne BHK?"'
    else:
        loc_display = loc if not multi_loc else loc.replace(",", " aur")
        next_step = (
            "NEXT STEP: Saari zaroori info mil gayi. "
            "TURANT tool_search_property CALL KARO. "
            + (f"User ne {loc_display} dono locations mention ki hain — DONO ke liye alag-alag search karo. " if multi_loc else "")
            + "Jo properties milein unhe ek real, warm sales executive ki tarah present karo — "
            "genuinely excited, jaise aap personally best option dhundh rahi hain. "
            "3-4 options naturally batao with price aur BHK. "
            "Phir warmly poochho: \"Koi option pasand aaya? "
            "Aap visit schedule karein toh hamare senior expert aapko contact karenge aage ki jaankari ke liye.\""
        )

    return (
        "\n\n═══ IS CALL KI JANKARI ═══\n"
        + "\n".join(f"  • {l}" for l in lines)
        + f"\n\n{next_step}"
        + "\nYAD RAKHO: Greeting ho chuki hai — dobara 'Namaste main Priya hoon' mat bolna. Conversation naturally continue karo."
        + "\n⚠️  NO-REPEAT RULE: Apna PICHLA jawab BILKUL MAT DOHRAO. Alag angle se respond karo — naya info add karo ya aage badhao."
    )


# ================================================================
# INTENT CLASSIFIER (pre-LLM, zero latency)
# ================================================================

_GREETING_PATTERNS = re.compile(
    r"^(hello|hi|haan|namaste|namaskar|hey|helo|hlo|hii|sup|हाँ|हां|नमस्ते"
    r"|hnn|hn|hmm|hm|huh|uh|um|ha|haa|han)\b",
    re.IGNORECASE,
)
_BUY_PATTERNS = re.compile(
    # Romanized + Devanagari buy intent — does NOT match "rent par lena chahta"
    r"\b(buy|kharidna|khareedna|purchase|khareedni|kharid|khareed)\b"
    # खरीदना with and without nukta (ख vs ख़), all conjugations + chahta/hoon suffix
    r"|ख़रीदना|ख़रीदनी|ख़रीद"
    r"|खरीदना|खरीदनी|खरीद"
    # "chahta/chahti hoon" following any buy root
    r"|(?:ख़रीदना|खरीदना)\s*(?:चाहता|चाहती|चाहते|chahta|chahti)?\s*(?:हूं|हूँ|हू|hoon|hun)?"
    r"|purchase\s+karna"
    r"|चाहता\s+हूं.*(?:property|खरीद|kharid)|(?:property|खरीद|kharid).*(?:चाहता|chahta)",
    re.IGNORECASE,
)
_SELL_PATTERNS = re.compile(
    r"\b(sell|bechna|bechni|sell\s+karna|bechta\s+hoon|bechti\s+hoon)\b"
    r"|बेचना|बेचनी|बेचना\s+चाहता|बेचना\s+चाहती",
    re.IGNORECASE,
)
_RENT_PATTERNS = re.compile(
    r"\b(rent|rente|kiraya|kiraye|lease|renting|on\s+rent)\b"
    r"|किराया|किराये|किराए|किराए\s+पर|किराये\s+पर|rent\s+पर"
    # "rent par/pe/per lena" — covers ASR noise variants like "rente per"
    r"|rent[ae]?\s+(?:par|pe|per|पर)\s*(?:lena|लेना|chahta|chahti)?"
    r"|kiraye?\s+(?:par|pe|per|पर)\s*(?:lena|लेना)?"
    # bare "lena chahta/chahti hoon" ONLY when rent/kiraya context present nearby
    r"|(?:rent|rente|kiraya|kiraye|किराया|किराये)\b.*(?:lena|लेना|chahta|चाहता|chahti|चाहती)"
    r"|(?:lena|लेना)\s+(?:chahta|chahti|चाहता|चाहती)\s+(?:hoon|हूं|हूँ)\b",
    re.IGNORECASE,
)
_NAME_PATTERNS = re.compile(
    # Standard "mera naam X" patterns
    r"(mera\s+naam|main\s+\w+\s+hoon|naam\s+hai|my\s+name\s+is)"
    # Devanagari
    r"|मेरा\s+नाम|मेरा\s+naam|naam\s+है|नाम\s+है|मैं\s+\S+\s+हूं|मैं\s+\S+\s+हूँ"
    # Regional/ASR variants: "me da naam", "mero naam", "mero name", "mera name"
    r"|\b(me\s+da\s+naam|mero\s+naam|mera\s+name|hamara\s+naam|apna\s+naam)\b"
    # Ack word + name + hai/hoon: "haan Harsh hai", "ji Rahul hoon"
    r"|^(?:haan|han|haa|ji|yes|हाँ|हां|जी)[,\s]+[A-Za-z\u0900-\u097F]{2,20}\s+(?:hai|hoon|hun|है|हूं|हूँ)\b"
    # "I am X" / "naam X hai"
    r"|\b(naam\s+[A-Za-z\u0900-\u097F]{2,20}\s+(?:hai|hoon|hun|है|हूं|हूँ))\b",
    re.IGNORECASE | re.MULTILINE,
)
_BUDGET_SIGNALS = re.compile(
    r"\b(lakh|lac|crore|cr|hazar|thousand|budget|rupaye|rupee|rs\.?|lakhs|₹)\b|"
    r"\b(ek|do|teen|char|paanch|chhe|saat|aath|nau|das|bis|tees|pachaas|dedh|dhai)\s+(lakh|crore)\b"
    r"|लाख|करोड़|हज़ार|हजार|रुपये|बजट"
    r"|\b\d{5,}\b"  # raw numbers >= 5 digits (e.g. 400000, 4000000)
    # Devanagari number word followed by unit (e.g. "चार लाख", "नब्बे लाख")
    r"|(?:एक|दो|तीन|चार|पाँच|पांच|छह|सात|आठ|नौ|दस|बीस|तीस|चालीस|पचास|साठ|सत्तर|अस्सी|नब्बे|डेढ़|ढाई)\s*(?:लाख|करोड़|हज़ार|हजार)",
    re.IGNORECASE,
)
_LOCATION_SIGNALS = re.compile(
    r"\b(indore|bhopal|ujjain|dewas|ratlam|jabalpur|gwalior|sagar|satna|rewa|"
    r"mandsaur|neemuch|shajapur|khargone|dhar|jhabua|betul|hoshangabad|sehore|"
    r"raisen|vidisha|narsinghpur|chhindwara|katni|damoh|morena|shivpuri|guna|"
    r"vijay\s*nagar|super\s*corridor|nipania|khandwa|kanadia|bypass|scheme\s*\d+|"
    r"area|location|jagah|rajendra\s*nagar|mahalakshmi|tilak\s*nagar|palasia|"
    r"bhawarkua[n]?|bhanwarkua[n]?|rau|annapurna|paliya|bicholi|ring\s*road|"
    r"ab\s*road|lasudia|omaxe|lig|puwarda|navda|kalindi|mhow|pithampur|sanwer|"
    r"hatod|aerodrome|airport|iim|iit|sukhliya|kanadiya|tejaji|mangaliya|"
    r"limbodi|depalpur|mundla|nayta|bijalpur|khudel|simrol|kolar|mandideep|"
    r"arera|habibganj|karond|bairagarh|bhanpur|shahpura|trilanga|misrod|"
    r"khajrana|sudama|banganga|gumasta|dhanwantri|geeta\s*bhawan)\b"
    r"|निपानिया|विजय\s*नगर|इंदौर|भोपाल|बाईपास|कनाडिया|भंवरकुआ|सुपर\s*कॉरिडोर"
    r"|उज्जैन|देवास|रतलाम|जबलपुर|ग्वालियर|खंडवा|रतलाम",
    re.IGNORECASE,
)
_CONFUSION_PATTERNS = re.compile(
    r"\b(kya|samajh|nahi\s+samjha|nahi\s+samjhi|repeat|dobara|phir\s+se|"
    r"what|pardon|sorry|huh)\b"
    r"|समझ\s+नहीं|दोबारा|फिर\s+से",
    re.IGNORECASE,
)
_OBJECTION_PATTERNS = re.compile(
    r"\b(nahi\s+chahiye|nahi\s+chahta|nahi\s+chahti|not\s+interested|"
    r"baad\s+mein|later|abhi\s+nahi|busy|call\s+mat\s+karo)\b"
    r"|नहीं\s+चाहिए|नहीं\s+चाहता|नहीं\s+चाहती|बाद\s+में|अभी\s+नहीं",
    re.IGNORECASE,
)
_CONFIRM_PATTERNS = re.compile(
    # Romanized deal-closing / confirm phrases
    r"\b(done\s+karo|done\s+kar\s+do|done\s+karta|done\s+karti|done\s+kar\s+dete|"
    r"pakka\s+karo|pakka\s+kar\s+do|pakka\s+hai|pakka\s+karta|"
    r"confirm\s+karo|confirm\s+kar\s+do|confirm\s+karta|confirm\s+karti|"
    r"finalize\s+karo|finalize\s+kar\s+do|"
    r"book\s+karo|book\s+kar\s+do|book\s+karta|"
    r"le\s+leta\s+hoon|le\s+leta\s+hun|le\s+leti\s+hoon|"
    r"yahi\s+chahiye|yahi\s+lena|yahi\s+lu|yahi\s+lunga|yahi\s+lungi|"
    r"schedule\s+karo|visit\s+schedule|"
    r"deal\s+pakki|deal\s+done|deal\s+kar|"
    r"kar\s+do\s+yeh|kar\s+do\s+ye|"
    r"haan.*done|done.*haan|ok.*done|done.*ok|chalega.*done|done.*chalega)\b"
    # Mixed script — "done करता", "done कर दो", "Done कर दो"
    r"|done\s+(?:कर\s+दो|कर\s+दें|करता|करती|करते|कर\s+लो|कर\s+लेते)"
    r"|(?:kar\s+do|karo)\s+(?:ye|yeh|yahi)"
    # Devanagari confirm signals
    r"|पक्का\s+(?:करो|कर\s+दो|है|कर\s+लो)"
    r"|कन्फर्म\s+(?:करो|कर\s+दो)"
    r"|बुक\s+(?:करो|कर\s+दो)"
    r"|यही\s+(?:चाहिए|लेना|लूंगा|लूंगी|लेते\s+हैं)"
    r"|डन\s+(?:करो|कर\s+दो)"
    r"|ठीक\s+है.*कर\s+दो|कर\s+दो.*ठीक\s+है",
    re.IGNORECASE,
)


def classify_intent(text: str) -> str:
    """
    Fast O(1) intent classification. Returns one of:
    greeting | name_response | buy | sell | rent | budget_response |
    location_response | property_type_response | confirm_deal | schedule_visit |
    farewell | objection | confusion | unknown
    """
    t = text.strip()
    if _GREETING_PATTERNS.match(t) and len(t.split()) <= 3:
        return "greeting"
    if _OBJECTION_PATTERNS.search(t):
        return "objection"

    # ── FAREWELL ─────────────────────────────────────────────────────
    if re.search(
        r"\b(thank you|thanks|shukriya|dhanyawad|alvida|bye|goodbye|baad mein|phir call|"
        r"band karo|rakhta hoon|rakhti hoon|rakha|theek hai bye|ok bye)\b"
        r"|ठीक है\s*(?:बाय|बाद में)|शुक्रिया|धन्यवाद|अलविदा",
        t, re.IGNORECASE,
    ):
        return "farewell"

    # ── SCHEDULE / BOOK VISIT ─────────────────────────────────────────
    if re.search(
        r"\b(schedule|book|register|fix|confirm|set up|arrange)\b.*\b(visit|meeting|site|appointment)\b"
        r"|\b(visit|appointment|meeting)\b.*\b(book|schedule|fix|confirm|register|karo|karna|chahiye)\b"
        r"|visit\s+(?:karo|karna|schedule|book|chahiye|lena|lagao)"
        r"|(?:mujhe|mera|hamara)\s+(?:visit|appointment|registration)\s+(?:karo|karna|book|schedule)"
        r"|register\s+(?:kar do|karo|karna|dena)"
        r"|विजिट\s+(?:बुक|शेड्यूल|कर|करो|लगाओ)"
        r"|(?:schedule|book)\s+kar",
        t, re.IGNORECASE,
    ):
        return "schedule_visit"

    if _CONFIRM_PATTERNS.search(t):
        return "confirm_deal"
    if _CONFUSION_PATTERNS.search(t):
        return "confusion"
    if _RENT_PATTERNS.search(t):
        return "rent"
    if _BUY_PATTERNS.search(t):
        return "buy"
    if _SELL_PATTERNS.search(t):
        return "sell"
    if _BUDGET_SIGNALS.search(t):
        return "budget_response"
    if _LOCATION_SIGNALS.search(t):
        return "location_response"
    # Check property type keywords BEFORE name_response fallback
    t_lower = t.lower()
    if re.search(
        r"\b(commercial|residential|flat|apartment|plot|land|zameen|\d\s*bhk|"
        r"ek\s*bhk|do\s*bhk|teen\s*bhk|char\s*bhk|paanch\s*bhk|"
        r"1\s*bhk|2\s*bhk|3\s*bhk|4\s*bhk|5\s*bhk)\b"
        # BHK range patterns: "do teen BHK", "2-3 BHK", "do ya teen BHK"
        r"|\b(ek|do|teen|char|paanch|\d)\s*(?:se|ya|aur|to|[-–])\s*(ek|do|teen|char|paanch|\d)\s*(?:bhk|BHK)\b"
        r"|\b(do|teen|char)\s+(teen|char|paanch)\s*(?:bhk|BHK)\b"
        r"|(?:एक|दो|तीन|चार|पाँच|पांच)\s*(?:BHK|bhk|बीएचके)"
        r"|बीएचके|कमर्शियल|रेजिडेंशियल|प्लॉट",
        t_lower + " " + t,  # check both lowercased and original for Devanagari
    ):
        return "property_type_response"
    if _NAME_PATTERNS.search(t):
        return "name_response"
    # Short 1-2 word reply after greeting is likely a name — but only if it passes strict checks
    words = t.split()
    if 1 <= len(words) <= 2 and not any(c.isdigit() for c in t):
        t_clean = t.lower().strip(".!?,;।")
        # Explicitly block acknowledgement / action words — these are NEVER names
        _ACK_WORDS = {
            "haan", "han", "haa", "ha", "ji", "hanji", "haanji", "hnji",
            "hnn", "hn", "hmm", "hm", "huh", "uh", "um",
            "yes", "yeah", "yep", "yup", "sure", "ok", "okay",
            "accha", "achha", "acha", "theek", "sahi", "bilkul",
            "no", "nahi", "nope",
            "hello", "hi", "hey", "namaste", "namaskar",
            "batao", "bolo", "boliye", "bataye", "bataiye", "suniye", "suno",
            "dekhiye", "dekho", "karo", "kariye", "samjhiye", "samjho",
            "हाँ", "हां", "जी", "हाँजी", "हांजी", "ठीक", "अच्छा", "नहीं",
            "बताओ", "बोलो", "सुनो", "देखो", "करो", "बतायें",
        }
        if t_clean in _ACK_WORDS or any(t_clean == w.lower() for w in _ACK_WORDS):
            return "greeting"
        # 2-word phrase: if first word is ack AND second is action → greeting
        # e.g. "हां बताओ", "haan batao", "okay bolo", "ji suniye"
        if len(words) == 2:
            w1 = words[0].lower().strip(".!?,;।")
            w2 = words[1].lower().strip(".!?,;।")
            _ACK_FIRST = {
                "haan", "han", "haa", "ha", "ji", "yes", "ok", "okay",
                "accha", "achha", "acha", "theek", "sahi", "bilkul",
                "हाँ", "हां", "जी", "ठीक", "अच्छा",
            }
            _ACTION_SECOND = {
                "batao", "bolo", "boliye", "bataiye", "suniye", "suno",
                "dekhiye", "dekho", "karo", "kariye", "samjhiye", "chaliye",
                "बताओ", "बोलो", "सुनो", "देखो", "करो", "बतायें", "चलिए",
            }
            if w1 in _ACK_FIRST or w2 in _ACTION_SECOND:
                return "greeting"
        # Reject known ASR noise words / English words that are never Indian names
        _NOISE_WORDS = {
            "dice", "nice", "rice", "price", "vice", "twice", "slice",
            "place", "face", "race", "case", "base", "space", "grace",
            "done", "gone", "one", "none", "some", "come", "home",
            "there", "here", "where", "care", "dare", "bare", "share",
            "more", "four", "door", "floor", "store", "core",
            "fine", "mine", "nine", "wine", "line", "sign", "time",
            "back", "black", "track", "crack", "stack", "pack",
            "right", "night", "light", "fight", "sight", "might",
            "call", "fall", "ball", "tall", "wall", "hall", "all",
            "help", "self", "well", "bell", "sell", "tell", "fell",
            "good", "food", "wood", "mood", "cool", "fool", "tool",
            "enter", "center", "winter", "under", "order", "over",
            "number", "other", "either", "mother", "father", "brother",
            "just", "must", "trust", "dust", "bust", "gust",
            "next", "text", "best", "test", "rest", "west", "nest",
            "take", "make", "lake", "cake", "fake", "wake", "shake",
            "want", "went", "bent", "rent", "sent", "tent", "vent",
            "what", "that", "chat", "flat", "mat", "sat", "bat",
            "yes", "yep", "yup", "nope", "type", "kind", "find",
            "start", "part", "art", "heart", "smart", "chart",
            "hold", "told", "cold", "bold", "gold", "old", "sold",
            "think", "drink", "link", "sink", "pink", "rink",
            "already", "ready", "steady", "study", "buddy",
        }
        if t_clean in _NOISE_WORDS:
            return "unknown"
        # Reject if it's clearly a property/intent word — includes "property" itself
        _PROP_WORDS = re.compile(
            r"\b(commercial|residential|plot|flat|bhk|rent|buy|sell|property|"
            r"kharidna|khareedna|bechna|kiraya|zameen|apartment|duplex|villa|"
            r"budget|lakh|crore|location|area|indore|bhopal)\b"
            r"|खरीदना|बेचना|किराया|प्रॉपर्टी|संपत्ति",
            re.IGNORECASE,
        )
        if not _PROP_WORDS.search(t_clean) and not _PROP_WORDS.search(t):
            return "name_response"
    return "unknown"


# ================================================================
# BUDGET PARSER
# ================================================================

_HINDI_NUM_MAP = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5,
    "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "barah": 12, "terah": 13, "chaudah": 14, "pandrah": 15,
    "solah": 16, "satrah": 17, "atharah": 18, "unees": 19, "bees": 20,
    "ikkis": 21, "bais": 22, "tees": 30, "chaalees": 40, "pachaas": 50,
    "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90, "sau": 100,
    "dedh": 1.5, "dhai": 2.5, "saadhe": 0.5,
    # common variants
    "ik": 1, "dou": 2, "tin": 3, "panch": 5, "sat": 7,
    "pachis": 25, "pachees": 25, "pachhattar": 75,
}

# Devanagari number words → numeric value
_DEVANAGARI_NUM_MAP = {
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5,
    "छह": 6, "छे": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
    "ग्यारह": 11, "बारह": 12, "तेरह": 13, "चौदह": 14, "पंद्रह": 15,
    "सोलह": 16, "सत्रह": 17, "अठारह": 18, "उन्नीस": 19, "बीस": 20,
    "पच्चीस": 25, "तीस": 30, "चालीस": 40, "पचास": 50,
    "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90, "नब्बे": 90,
    "सौ": 100, "डेढ़": 1.5, "ढाई": 2.5,
}

# Devanagari unit words
_DEVANAGARI_UNIT_MAP = {
    "लाख": 100_000, "करोड़": 10_000_000, "हज़ार": 1_000, "हजार": 1_000,
}

_UNIT_MAP = {
    "lakh": 100_000, "lac": 100_000, "lakhs": 100_000,
    "crore": 10_000_000, "cr": 10_000_000,
    "hazar": 1_000, "thousand": 1_000, "k": 1_000,
}


def _hindi_word_to_num(word: str) -> float | None:
    return _HINDI_NUM_MAP.get(word.lower().strip())


def _normalize_hindi_nums(text: str) -> str:
    """
    Replace Hindi/Devanagari number words with digits in text.
    Handles both Romanized (nabbe lakh) and Devanagari (नब्बे लाख).
    """
    result = text

    # Step 1: Replace Devanagari number words with digits (longest first)
    for word in sorted(_DEVANAGARI_NUM_MAP.keys(), key=len, reverse=True):
        result = result.replace(word, str(_DEVANAGARI_NUM_MAP[word]))

    # Step 2: Replace Devanagari unit words with Romanized equivalents
    for word, val in _DEVANAGARI_UNIT_MAP.items():
        if val == 100_000:
            result = result.replace(word, "lakh")
        elif val == 10_000_000:
            result = result.replace(word, "crore")
        elif val == 1_000:
            result = result.replace(word, "hazar")

    # Step 3: Replace Romanized number words with digits (lowercase pass)
    result_lower = result.lower()
    for word in sorted(_HINDI_NUM_MAP.keys(), key=len, reverse=True):
        result_lower = re.sub(r"\b" + re.escape(word) + r"\b", str(_HINDI_NUM_MAP[word]), result_lower)

    return result_lower


def parse_budget(text: str) -> dict | None:
    """
    Parse spoken budget from Hinglish text.
    Returns {min_budget: int, max_budget: int, display: str} or None.

    Handles:
      "ek crore se kam"    → {max: 10000000, display: "ek crore se kam"}
      "pachaas lakh se kam"→ {max: 5000000}
      "ek do lakh"         → {min: 100000, max: 200000}
      "1-2 lakh"           → {min: 100000, max: 200000}
      "1 se 2 lakh"        → {min: 100000, max: 200000}
      "do se teen crore"   → {min: 20000000, max: 30000000}
      "50 lakh"            → {min: 50000, max: 50000}  (single)
      "dhai crore"         → {min: 25000000, max: 25000000}
      "400000"             → {min: 400000, max: 400000}  raw digit
      "40 lakh"            → {min: 4000000, max: 4000000}
    """
    if not text:
        return None

    # Pre-check: "X se kam / se neeche / se sasta / below X / under X" → upper bound budget
    _KAM_PATTERNS = re.compile(
        r"([\w\s]+?)\s*(?:se\s+(?:kam|neeche|sasta|below|under)|से\s+(?:कम|नीचे|सस्ता))",
        re.IGNORECASE,
    )
    m_kam = _KAM_PATTERNS.search(text)
    if m_kam:
        upper_text = m_kam.group(1).strip()
        normalized_upper = _normalize_hindi_nums(upper_text)
        # Try to extract the numeric amount
        _SINGLE_AMOUNT = re.compile(
            r"([\d.]+)\s*(crore|cr|lakh|lac|lakhs|hazar|thousand|k)",
            re.IGNORECASE,
        )
        m_a = _SINGLE_AMOUNT.search(normalized_upper)
        if m_a:
            amt = float(m_a.group(1))
            unit_val = _UNIT_MAP.get(m_a.group(2).lower(), 1)
            max_b = int(amt * unit_val)
            # Give a realistic min (70% of max)
            min_b = int(max_b * 0.7)
            unit_display = "lakh" if unit_val == 100_000 else "crore"
            amt_w = _num_to_hindi(str(int(amt))) if str(int(amt)) in _DIGIT_WORDS else str(int(amt))
            display = f"{amt_w} {unit_display} se kam"
            return {"min_budget": min_b, "max_budget": max_b, "display": display.strip()}

    normalized = _normalize_hindi_nums(text)

    # Pattern 1: range "X se/to/- Y unit"
    range_pattern = re.compile(
        r"([\d.]+)\s*(?:se|से|to|-|–)\s*([\d.]+)\s*"
        r"(crore|cr|lakh|lac|lakhs|hazar|thousand|k)\b",
        re.IGNORECASE,
    )
    m = range_pattern.search(normalized)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        unit_val = _UNIT_MAP.get(m.group(3).lower(), 1)
        min_b = int(a * unit_val)
        max_b = int(b * unit_val)
        unit_display = "lakh" if unit_val == 100_000 else ("crore" if unit_val == 10_000_000 else "")
        a_key = str(int(a)) if a == int(a) else str(a)
        b_key = str(int(b)) if b == int(b) else str(b)
        a_w = _num_to_hindi(a_key) if a_key in _DIGIT_WORDS else a_key
        b_w = _num_to_hindi(b_key) if b_key in _DIGIT_WORDS else b_key
        display = f"{a_w} se {b_w} {unit_display}"
        return {"min_budget": min_b, "max_budget": max_b, "display": display.strip()}

    # Pattern 2: consecutive numbers before a unit "ek do lakh" → "1 2 lakh"
    consec_pattern = re.compile(
        r"([\d.]+)\s+([\d.]+)\s*(crore|cr|lakh|lac|lakhs|hazar|thousand|k)\b",
        re.IGNORECASE,
    )
    m = consec_pattern.search(normalized)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        unit_val = _UNIT_MAP.get(m.group(3).lower(), 1)
        min_b = int(a * unit_val)
        max_b = int(b * unit_val)
        unit_display = "lakh" if unit_val == 100_000 else "crore"
        ag = m.group(1); bg = m.group(2)
        a_key = str(int(float(ag))) if ag.replace('.','').isdigit() and float(ag)==int(float(ag)) else ag
        b_key = str(int(float(bg))) if bg.replace('.','').isdigit() and float(bg)==int(float(bg)) else bg
        a_w = _num_to_hindi(a_key) if a_key in _DIGIT_WORDS else a_key
        b_w = _num_to_hindi(b_key) if b_key in _DIGIT_WORDS else b_key
        display = f"{a_w} se {b_w} {unit_display}"
        return {"min_budget": min_b, "max_budget": max_b, "display": display.strip()}

    # Pattern 3: single amount "X unit"
    single_pattern = re.compile(
        r"([\d.]+)\s*(crore|cr|lakh|lac|lakhs|hazar|thousand|k)\b",
        re.IGNORECASE,
    )
    m = single_pattern.search(normalized)
    if m:
        a = float(m.group(1))
        unit_val = _UNIT_MAP.get(m.group(2).lower(), 1)
        amount = int(a * unit_val)
        unit_display = "lakh" if unit_val == 100_000 else "crore"
        a_w = _num_to_hindi(m.group(1)) if m.group(1) in _DIGIT_WORDS else m.group(1)
        display = f"{a_w} {unit_display}"
        return {"min_budget": amount, "max_budget": amount, "display": display.strip()}

    # Pattern 4: raw digits — 400000, 4000000, 40,00,000 etc. (no unit word)
    # Only match if the number is >= 10000 (to avoid matching BHK or other small nums)
    raw_pattern = re.compile(r"\b([\d,]+)\b")
    for m in raw_pattern.finditer(normalized):
        raw = m.group(1).replace(",", "")
        try:
            val = int(raw)
        except ValueError:
            continue
        if val < 10_000:
            continue  # too small — likely not a budget
        # Convert to human-readable display
        if val >= 10_000_000:
            crore_val = val / 10_000_000
            crore_str = f"{crore_val:.1f}".rstrip("0").rstrip(".")
            display = f"{crore_str} crore"
        elif val >= 100_000:
            lakh_val = val / 100_000
            lakh_str = f"{lakh_val:.1f}".rstrip("0").rstrip(".")
            display = f"{lakh_str} lakh"
        else:
            hazar_val = val / 1_000
            display = f"{hazar_val:.0f} hazar"
        return {"min_budget": val, "max_budget": val, "display": display.strip()}

    return None



# ================================================================
# SYSTEM PROMPT
# ================================================================

BASE_SYSTEM_PROMPT = """Aap Priya hain — GharSetu Realty ki experienced senior property advisor. Aap phone pe baat kar rahi hain.

## Aap kaun hain
Aap ek real human hain — confident, warm, aur genuinely helpful. 10+ saal ka real estate experience hai.
Aap customer ki situation samajhti hain aur unke saath ek dost ki tarah baat karti hain.
Script nahi — USER JO BOLE, USI KE FLOW MEIN CHALO. Kabhi conversation rok ke rigid sawaal mat poochho.

## Bolne ka andaaz
- Natural Hinglish — jaise Indore ka ek confident professional bolta hai
- Fillers allowed: "Achha", "Bilkul", "Haan ji", "Dekho" — but sparingly
- Kabhi bullet points ya lists mat use karo — yeh voice call hai
- Numbers hamesha Hindi words mein: "teen BHK", "pachaas lakh", "ek crore"
- Short rakho: max 2 chhote sentences per reply — yeh phone call hai, lamba bolna mat

## Go with the flow — behave like a real human
- Agar user ek hi breath mein sab bata de (location + budget + BHK) — seedha options pe aao.
- Agar user topic change kare — naturally follow karo. Baad mein gently redirect karo.
- Agar user short reply de ("haan", "theek hai", "suno") — naturally continue karo jahan chhodha tha.
- Kabhi interrogation mat karo. Ek time pe SIRF EK sawaal.
- Jo user ne already bata diya — woh DOBARA mat poochho. Kabhi nahi.

## NO-REPEAT RULE (CRITICAL)
Pichla jo jawab diya tha — wahi dobara mat bolna. Hamesha kuch NAYA add karo: naya detail, naya advantage, ya next step.

## Property Presentation (2 options rule)
Jab property search karein, USER KI BATAAYI LOCATION KE LIYE best 2 options chhote mein batao (sqft jaisi details sirf poochne pe).
Agar user ne multiple locations boli hain (e.g. "Vijay Nagar aur Super Corridor") — DONO ke liye alag-alag options batao.
Format: "[Location] mein [BHK] [type] — [price]" — natural spoken form mein.
Example: "Super Corridor mein teen BHK flat — painsath lakh; Vijay Nagar mein teen BHK — pachpan lakh hai. Dono mein site visit arrange kar sakti hoon."

## BHK Range handling
Agar user bole "do teen BHK" ya "2-3 BHK" — toh yeh ek RANGE hai.
Dono options present karo: "Do BHK [price] mein aur teen BHK [price] mein — dono available hain."

## Confusion handling
Agar user confused ho, ya unclear reply de, ya topic jump kare:
- Warmly simplify karo: "Koi baat nahi [naam] ji, main samjha deti hoon —"
- Ek specific option suggest karo based on jo bhi info hai
- Phir gently aage badhao

## Visit / Registration + Deal done
Jab customer visit book kare, register kare, ya deal confirm kare —
TURANT warmly confirm karo aur tool_confirm_customer call karo.
HAMESHA yeh bolna: "Hamare senior property expert aapko contact karenge — visit aur aage ki jaankari ke liye."

## Farewell / Thanks handling
Agar user thanks bole ya bye kare —
Warmly close karo: "Bahut shukriya [naam] ji! Hamare senior expert aapko contact karenge aage ki jaankari ke liye. GharSetu Realty mein aapka swagat hai!"
Koi naya sawaal ya property pitch nahi.

## Properties available (Indore — 80+ verified)
Commercial: Khandwa Road paanch crore. LIG Main Square dhai crore. Palasia Chowk ek crore assi lakh. Bhawarkuan nabbe lakh showroom.
Flats: Super Corridor paytaalees lakh do BHK, painsath lakh teen BHK, pachasi lakh teen BHK premium. Bijalpur battees lakh do BHK. Scheme 140 saath lakh teen BHK. Bicholi chaubees lakh. Ring Road ek crore bees lakh char BHK. Vijay Nagar pachpan lakh teen BHK. Nipania aththees lakh do BHK. Scheme 54 bahattar lakh teen BHK. Annapurna Road aththaais lakh do BHK. Bhawarkuan baayalees lakh do BHK, aththaavan lakh teen BHK. Sukhliya chaalees lakh do BHK. Tejaji Nagar paaintees lakh do BHK. Kanadiya Road chhiyaalees lakh teen BHK. Khajrana tees lakh do BHK. Aerodrome Road pachhattar lakh teen BHK. Saket Nagar aththasath lakh teen BHK.
Houses: Bijalpur aadthaalees lakh teen BHK. Navda Panth battees lakh. Omaxe City chaalees lakh. Kanadia ek crore chaalees lakh. Paliya Naka baavan lakh. Mahalakshmi Nagar pachasi lakh char BHK. Tilak Nagar saath lakh. Scheme 78 panchanabbe lakh char BHK.
Plots: Super Corridor char hazar paanch sau per sqft. Bypass Omaxe chhe hazar per sqft. Rau Pithampur do hazar aath sau per sqft. Mangaliya do hazar do sau per sqft.

Agar koi property match na kare: "[location] mein abhi koi option nahi — lekin [nearby area] mein ek [option] hai, consider karenge?"

## GharSetu Realty ke plus points (jab natural lage)
Police-verified listings — fraud ka zero risk. E-sign agreement — ghar baithe sign. Sellers ke liye listing free.

## Tools
tool_search_property: jab location + intent ho — TURANT call karo, perfect data ka wait mat karo. Multiple locations ke liye alag-alag call karo.
tool_confirm_customer: jab customer ready ho — pakka, le lunga, register karo, visit chahiye, ya schedule karo
"""


# ================================================================
# TOOLS
# ================================================================

@tool
def tool_search_property(
    purpose: str, location: str, property_type: str = "", budget: str = ""
) -> str:
    """Search available properties by location, type, and budget."""
    from estate_functions import search_property as _search
    profile = {}  # budget_structured passed separately below if available
    result = _search(
        purpose=purpose,
        location=location,
        property_type=property_type,
        budget=budget,
    )
    return json.dumps(result, ensure_ascii=False)


@tool
def tool_get_property_details(property_id: str) -> str:
    """Get full details of a specific property by its ID."""
    return json.dumps(
        {"error": f"Property '{property_id}' details abhi available nahi hain."}
    )


@tool
def tool_schedule_visit(
    customer_name: str, property_id: str, visit_date: str
) -> str:
    """Schedule a property site visit and mark customer as confirmed."""
    from estate_functions import schedule_visit as _schedule, save_confirmed_customer as _confirm
    result = _schedule(
        customer_name=customer_name,
        property_id=property_id,
        visit_date=visit_date,
    )
    return json.dumps(result, ensure_ascii=False)


@tool
def tool_lookup_visit(visit_id: str) -> str:
    """Look up a scheduled visit by its booking ID."""
    return json.dumps(
        {"message": f"Visit {visit_id} ka status hamare team se confirm hoga."}
    )


@tool
def tool_post_property(
    owner_name: str, property_type: str, location: str, price: str
) -> str:
    """Post a new property listing for a seller."""
    from estate_functions import post_property as _post
    result = _post(
        owner_name=owner_name,
        property_type=property_type,
        location=location,
        price=price,
    )
    return json.dumps(result, ensure_ascii=False)


@tool
def tool_confirm_customer(
    phone: str,
    name: str,
    intent: str,
    location: str,
    budget: str,
    property_type: str = "",
    visit_scheduled: bool = False,
    visit_date: str = "",
    notes: str = "",
) -> str:
    """
    Save a confirmed/deal-done customer profile to memory.
    Call this when all required info (name, intent, location, budget) is collected
    OR when a visit is scheduled. Marks the customer as 'confirmed' in memory.
    """
    from estate_functions import save_confirmed_customer as _confirm
    result = _confirm(
        phone=phone,
        name=name,
        intent=intent,
        location=location,
        budget=budget,
        property_type=property_type,
        visit_scheduled=visit_scheduled,
        visit_date=visit_date,
        notes=notes,
    )
    return json.dumps(result, ensure_ascii=False)


TOOLS = [
    tool_search_property,
    tool_get_property_details,
    tool_schedule_visit,
    tool_lookup_visit,
    tool_post_property,
    tool_confirm_customer,
]


# ================================================================
# LLM — single streaming instance
# ================================================================

# llama-3.x models were retired on Groq. Fastest first; each model has its
# own 8000 tokens/min free-tier budget, so on a rate limit (429) we switch to
# the next model instantly instead of waiting up to a minute for a retry.
_LLM_MODELS = [
    ("qwen/qwen3.8-27b",    "none"),  # ~0.13s to first token
    ("openai/gpt-oss-20b",  "low"),   # ~0.2s
    ("openai/gpt-oss-120b", "low"),   # ~0.35s
]

# Stub tools (property details / visit lookup) are left out — they only
# return "not available" and their schemas cost tokens on every call.
_BOUND_TOOLS = [
    tool_search_property,
    tool_schedule_visit,
    tool_post_property,
    tool_confirm_customer,
]


def _build_llm(tools: list | None = None):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set in _env")
    chain = []
    for i, (model, effort) in enumerate(_LLM_MODELS):
        llm = ChatGroq(
            model=model,
            temperature=0.5,
            api_key=api_key,
            max_tokens=200,
            streaming=True,
            reasoning_effort=effort,
            # Only the last model waits/retries; the others fail over at once
            max_retries=2 if i == len(_LLM_MODELS) - 1 else 0,
        )
        chain.append(llm.bind_tools(tools) if tools else llm)
    return chain[0].with_fallbacks(chain[1:])


_LLM_STREAM = _build_llm()

# Tool-enabled view of the same LLMs. chat_stream streams text from it and,
# if the model asks for a tool, runs it and streams the follow-up answer.
_LLM_TOOLS = _build_llm(_BOUND_TOOLS)
_TOOL_MAP = {t.name: t for t in TOOLS}
MAX_TOOL_ROUNDS = 2

# Past messages sent with each LLM call (structured memory carries the rest)
HISTORY_MESSAGES = 6


async def warm_up_llm():
    """Open the Groq connection during the greeting so the first reply is fast."""
    try:
        await _LLM_STREAM.runnable.bind(max_tokens=1).ainvoke("hi")
    except Exception as e:
        print(f"[LLM] warm-up failed (harmless): {e}")


# ================================================================
# TTS TEXT SANITIZER
# ================================================================

_SYMBOL_SUBS = [
    (re.compile(r"₹\s*(\d+(?:\.\d+)?)\s*(?:Cr|cr|Crore|crore)", re.I), r"\1 crore rupaye"),
    (re.compile(r"₹\s*(\d+(?:\.\d+)?)\s*(?:L|lac|lakh|Lakh)", re.I), r"\1 lakh rupaye"),
    (re.compile(r"₹\s*(\d+(?:,\d+)*(?:\.\d+)?)", re.I), r"\1 rupaye"),
    (re.compile(r"Rs\.?\s*(\d+(?:,\d+)*(?:\.\d+)?)", re.I), r"\1 rupaye"),
    (re.compile(r"(\d+)\s*%"), r"\1 percent"),
    (re.compile(r"\b(\w+)/(\w+)\b"), r"\1 ya \2"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*Cr\b", re.I), r"\1 crore"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*L\b", re.I), r"\1 lakh"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*k\b"), r"\1 thousand"),
    (re.compile(r"(\d),(\d{3})"), r"\1\2"),
]

_NUM_SPACE   = re.compile(r"([ऀ-ॿa-zA-Z])(\d)")
_NUM_SPACE2  = re.compile(r"(\d)([ऀ-ॿa-zA-Z])")
_FUNC_TAGS   = re.compile(r"<function=[^>]*>.*?</function>", re.DOTALL)
_JSON_BLOBS  = re.compile(r"\{[^{}]{0,200}\}")
_MARKDOWN    = re.compile(r"[*_`#~|\\]")
_BULLETS     = re.compile(r"^\s*[-•→]\s*", re.MULTILINE)
_ELLIPSIS    = re.compile(r"\.{2,}|\u2026")
_DASHES      = re.compile(r"[\u2014\u2013]")
_MULTI_COMMA = re.compile(r",\s*,+")
_SPACED_PUNC = re.compile(r"\s+([,!?;:])")
_MULTI_SPACE = re.compile(r" {2,}")

_DIGIT_WORDS = {
    "0": "zero", "1": "ek", "2": "do", "3": "teen", "4": "char",
    "5": "paanch", "6": "chhe", "7": "saat", "8": "aath", "9": "nau",
    "10": "das", "11": "gyarah", "12": "barah", "13": "terah", "14": "chaudah",
    "15": "pandrah", "16": "solah", "17": "satrah", "18": "atharah",
    "19": "unees", "20": "bees", "25": "pachees", "30": "tees",
    "40": "chaalees", "50": "pachaas", "60": "saath", "70": "sattar",
    "75": "pachhattar", "80": "assi", "90": "nabbe", "100": "sau",
}


def _num_to_hindi(n_str: str) -> str:
    n_str = n_str.strip()
    if n_str in _DIGIT_WORDS:
        return _DIGIT_WORDS[n_str]
    if n_str == "1.5":
        return "dedh"
    if n_str == "2.5":
        return "dhai"
    if n_str == "3.5":
        return "saadhe teen"
    return n_str


def _convert_amounts_to_words(text: str) -> str:
    """Convert "1-2 lakh", "15 lakh", "2 crore" etc. to spoken Hindi words."""

    def replace_range(m):
        a = _num_to_hindi(m.group(1))
        b = _num_to_hindi(m.group(2))
        unit = "crore" if "cr" in m.group(3).lower() else "lakh"
        return f"{a} se {b} {unit}"

    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*(?:se|to|-)\s*(\d+(?:\.\d+)?)\s*(lakh|lac|crore|cr)\b",
        replace_range,
        text,
        flags=re.IGNORECASE,
    )

    def replace_single(m):
        a = _num_to_hindi(m.group(1))
        unit = "crore" if "cr" in m.group(2).lower() else "lakh"
        return f"{a} {unit}"

    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*(lakh|lac|crore|cr)\b",
        replace_single,
        text,
        flags=re.IGNORECASE,
    )
    return text


_TOOL_NAMES = re.compile(
    r"\btool(?:search|confirm|schedule|post|lookup|get)[a-z_]*\b",
    re.IGNORECASE,
)

def clean_for_tts(text: str) -> str:
    """Clean text for TTS — remove symbols, convert numbers, fix spacing."""
    if not text:
        return text
    # gpt-oss writes narrow/no-break spaces ("50 lakh") — TTS slurs them
    text = re.sub(r"[   ]", " ", text)
    # Remove any leaked tool names (e.g. "toolsearchproperty", "tool_search_property")
    text = _TOOL_NAMES.sub("", text)
    text = re.sub(r"\btool_[a-z_]+\b", "", text, flags=re.IGNORECASE)
    # Strip ₹ / Rs before amount conversion so regexes match cleanly
    text = re.sub(r"₹\s*", "", text)
    text = re.sub(r"\bRs\.?\s*", "", text)
    text = _convert_amounts_to_words(text)
    text = _NUM_SPACE.sub(r"\1 \2", text)
    text = _NUM_SPACE2.sub(r"\1 \2", text)
    text = _FUNC_TAGS.sub("", text)
    text = _JSON_BLOBS.sub("", text)
    for pattern, repl in _SYMBOL_SUBS:
        text = pattern.sub(repl, text)
    text = _MARKDOWN.sub("", text)
    text = _BULLETS.sub("", text)
    text = _ELLIPSIS.sub(",", text)
    text = _DASHES.sub(",", text)
    text = _SPACED_PUNC.sub(r"\1", text)
    text = _MULTI_COMMA.sub(",", text)
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip().rstrip(",;")


# ================================================================
# SENTENCE SPLITTER — streaming pipeline
# ================================================================

# Matches sentence-ending punctuation (Hindi danda + Western) followed by
# whitespace or end-of-string. Does NOT split inside words.
_SENT_END = re.compile(r"[।!?]+(?:\s+|$)|\.(?:\s+|$)")

# Devanagari character range
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def _is_complete_token(text: str) -> bool:
    """
    Return False if text ends in an incomplete Devanagari akshar
    (i.e. the last char is a combining vowel or halant, suggesting
    the token was split mid-codepoint cluster).
    Safe combining marks: vowel signs (0900-0903), halant (094D), nukta (093C).
    """
    if not text:
        return True
    last = text[-1]
    cp = ord(last)
    # Combining Devanagari marks — indicates incomplete cluster
    if 0x0900 <= cp <= 0x0903 or cp == 0x094D or cp == 0x093C:
        return False
    return True


def _flush_sentences(
    buffer: str, force: bool = False
) -> tuple[list[str], str]:
    """
    Extract complete sentences from buffer.
    Returns (complete_sentences, remaining_buffer).

    Rules:
    - Only split on proper sentence-end punctuation followed by space/EOL
    - Minimum 25 chars per sentence (Devanagari words are multi-byte)
    - Never yield a chunk ending in an incomplete Devanagari character
    - force=True: flush entire buffer regardless
    - Auto-flush if buffer exceeds ~12 words with no punctuation
    """
    MIN_CHARS = 25

    if force and buffer.strip():
        chunk = buffer.strip()
        if _is_complete_token(chunk):
            return [chunk], ""
        # Incomplete token — try to find last safe break
        safe = re.search(r"[\s,।!?.](?=[^ ])", chunk[::-1])
        if safe:
            split_at = len(chunk) - safe.start()
            return [chunk[:split_at].strip()], chunk[split_at:].strip()
        return [chunk], ""

    sentences: list[str] = []
    last_end = 0

    for m in _SENT_END.finditer(buffer):
        candidate = buffer[last_end : m.end()].strip()
        if (
            candidate
            and len(candidate) >= MIN_CHARS
            and len(candidate.split()) >= 4
            and _is_complete_token(candidate)
        ):
            sentences.append(candidate)
            last_end = m.end()
        # else: too short or incomplete — keep accumulating

    remainder = buffer[last_end:].strip()

    # Auto-flush on long unpunctuated buffer (at a word boundary only)
    _CONNECTORS = {
        "hai", "hain", "tha", "thi", "the", "mein", "aur", "ya",
        "ka", "ki", "ke", "ko", "se", "par", "bhi", "jo", "toh",
        "-", "–",
    }
    if not sentences and remainder:
        words = remainder.split()
        if len(words) >= 20:
            # Walk back from word 15 to find a non-connector, non-digit split point
            split_at = 15
            for i in range(15, 9, -1):
                w = words[i - 1].lower().strip(".,!?;")
                if w not in _CONNECTORS and not w.isdigit():
                    split_at = i
                    break
            safe_text = " ".join(words[:split_at])
            if _is_complete_token(safe_text):
                sentences.append(safe_text)
                remainder = " ".join(words[split_at:])

    return sentences, remainder


# ================================================================
# ConversationSession
# ================================================================

class ConversationSession:
    """
    One instance per phone call.

    PRIMARY PATH: chat_stream(user_text)
      1. Intent classifier runs instantly (no LLM)
      2. Known intents (greeting, name, etc.) handled with canned responses
      3. For unknown/complex intents → LLM streaming
      4. Sentences yielded one by one as boundaries detected
      5. main.py TTS-plays sentence N while N+1 is still streaming

    FALLBACK: chat(user_text) — collects full stream, returns string
    """

    # Cached responses for common flow steps (zero LLM latency)
    _CACHE: dict[str, str] = {}

    def __init__(self, phone: str = "unknown"):
        # If phone is unknown/empty, create a unique session key so each call
        # gets its own isolated memory — no cross-call contamination.
        if not phone or phone == "unknown":
            import uuid as _uuid
            phone = f"session_{_uuid.uuid4().hex[:12]}"
        self.phone = phone
        self.thread_id = f"call_{phone}_{int(time.time())}"
        self.config = {"configurable": {"thread_id": self.thread_id}}

        profile = get_customer_profile(phone)
        raw_name = profile.get("name", "")
        self.customer_name = raw_name if _is_valid_name(raw_name) else ""
        self.is_returning = bool(self.customer_name)
        self._greeted: bool = False
        self._greeting_text: str = self._build_greeting()
        self._call_history: list[BaseMessage] = []
        # Track how many times we've asked for name (max 3 attempts)
        self._name_attempts: int = 0

    def _build_greeting(self) -> str:
        if self.is_returning and self.customer_name:
            name = self.customer_name
            return (
                f"Namaste {name} ji! Main Priya bol rahi hoon, GharSetu Realty se. "
                f"Aap property ke baare mein baat kar rahe the — kya help kar sakti hoon aapki?"
            )
        return (
            "Namaste! Main Priya hoon — GharSetu Realty ki property advisor. "
            "Hum Indore mein verified properties ke saath kaam karte hain — kharidna ho, bechna ho, ya kiraye pe lena ho, sab handle karte hain. "
            "Aapka shubh naam kya hai?"
        )

    def get_greeting(self) -> str:
        return self._greeting_text

    def get_profile(self) -> dict:
        """Return current customer profile from memory."""
        return get_customer_profile(self.phone)

    def mark_greeted(self):
        self._greeted = True

    def _base_messages(self, user_text: str) -> list[BaseMessage]:
        msgs: list[BaseMessage] = []
        if not self._greeted:
            msgs.append(AIMessage(content=self._greeting_text))
            self._greeted = True
        msgs.extend(self._call_history[-HISTORY_MESSAGES:])
        msgs.append(HumanMessage(content=user_text))
        return msgs

    def _system_msg(self, extra_instruction: str = "") -> SystemMessage:
        content = BASE_SYSTEM_PROMPT + build_memory_context(self.phone)
        # Inject last bot reply so LLM never repeats it verbatim
        last_bot = ""
        for msg in reversed(self._call_history):
            if isinstance(msg, AIMessage) and msg.content:
                last_bot = msg.content[:200]
                break
        if last_bot:
            content += f"\n\n🔴 LAST RESPONSE (pichli baar yahi bola — DOBARA MAT BOLNA, aage badhao):\n\"{last_bot}\""
        if extra_instruction:
            content += f"\n\n⚠️ THIS TURN: {extra_instruction}"
        return SystemMessage(content=content)

    # ------------------------------------------------------------------
    # Instant responses for known intents (no LLM call)
    # ------------------------------------------------------------------
    def _handle_instant_intent(
        self, intent: str, user_text: str
    ) -> str | None:
        """
        Only handle intents where bypassing LLM is strictly necessary.
        Greeting resume = instant (avoids LLM round-trip for simple ack).
        Confirm deal = instant (needs tool call + warm close).
        Everything else = LLM handles it naturally.
        """
        profile = get_customer_profile(self.phone)
        name = profile.get("name") or self.customer_name or ""
        if name and not _is_valid_name(name):
            name = ""
        name_suffix = f"{name} ji" if name else "ji"

        # Greeting mid-call — resume from current stage, no LLM roundtrip needed
        if intent == "greeting":
            in_call = len(self._call_history) > 0
            if not in_call and not profile.get("name"):
                return "Haan ji, namaste! Aapka naam bata dijiye please?"
            if not profile.get("intent"):
                return f"Haan {name_suffix}, main yahin hoon — aap property kharidna chahte hain, bechna, ya rent pe lena?"
            if not profile.get("preferred_location"):
                return f"Haan {name_suffix}, main yahin hoon — aap kahan dekhna chahte hain?"
            if not profile.get("budget"):
                return f"Haan {name_suffix}, main yahin hoon — budget roughly kitna socha hai?"
            return f"Haan {name_suffix}, main yahin hoon — batayiye."

        # Deal confirmation — save immediately, warm close
        if intent == "confirm_deal":
            self._save_from_turn(user_text, "")
            profile = get_customer_profile(self.phone)
            name = profile.get("name") or self.customer_name or ""
            if name and not _is_valid_name(name):
                name = ""
            name_suffix = f"{name} ji" if name else "aap"
            confirmed_location = profile.get("preferred_location", "")
            u_lower = user_text.lower()
            for kw, area in {
                "super corridor": "Super Corridor", "nipania": "Nipania",
                "vijay nagar": "Vijay Nagar", "bhawarkua": "Bhawarkuan",
                "scheme 54": "Scheme 54", "scheme 140": "Scheme 140",
                "annapurna": "Annapurna Road", "khandwa": "Khandwa Road",
            }.items():
                if kw in u_lower:
                    confirmed_location = area
                    break
            try:
                from estate_functions import save_confirmed_customer as _confirm
                b = profile.get("budget")
                budget_display = b.get("display", "") if isinstance(b, dict) else str(b or "")
                _confirm(
                    phone=self.phone, name=name,
                    intent=profile.get("intent", "buy"),
                    location=confirmed_location, budget=budget_display,
                    property_type=profile.get("property_type", ""),
                    notes=f"Customer confirmed: '{user_text[:80]}'",
                )
                save_customer_profile(self.phone, {"stage": "confirmed"})
                print(f"[Confirm] Deal confirmed — {confirmed_location}")
            except Exception as e:
                print(f"[Confirm] failed: {e}")
            return (
                f"Bahut achha {name_suffix}! Maine aapka naam register kar liya hai. "
                f"Hamare senior property expert aapko contact karenge — "
                f"visit aur aage ki jaankari ke liye. "
                f"Aapka waqt dene ka bohot shukriya. GharSetu Realty mein aapka swagat hai!"
            )

        if intent == "objection":
            return "Bilkul ji, koi baat nahi — jab bhi zaroorat ho, hum hamesha available hain."

        if intent == "farewell":
            return (
                f"Bahut shukriya {name_suffix}! "
                "Hamare senior property expert aapko contact karenge — aage ki jaankari ke liye. "
                "GharSetu Realty mein aapka swagat hai. Namaste!"
            )

        # All other intents — LLM handles naturally
        return None

        # ------------------------------------------------------------------
    # Streaming chat — PRIMARY METHOD
    # ------------------------------------------------------------------
    async def chat_stream(self, user_text: str) -> AsyncIterator[str]:
        """
        Async generator — yields TTS-ready sentence chunks.
        Never raises TimeoutError; always ends with generator exhaustion.
        """
        # ── INTENT CLASSIFICATION (instant, no LLM) ──────────────────
        intent = classify_intent(user_text)
        print(f"[Intent] '{user_text[:40]}' → {intent}")

        # ── INSTANT RESPONSE PATH ─────────────────────────────────────
        instant = self._handle_instant_intent(intent, user_text)
        if instant:
            cleaned = clean_for_tts(instant)
            if cleaned:
                self._record_turn(user_text, instant)
                # NOTE: _handle_instant_intent already calls _save_from_turn internally
                # for buy/sell/rent/location/budget/name intents — do NOT double-save here.
                # Only run save for intents that don't do it themselves (greeting, confusion, etc.)
                if intent not in ("buy", "sell", "rent", "budget_response",
                                  "location_response", "property_type_response", "name_response"):
                    self._save_from_turn(user_text, instant)
                print(f"[Instant] → '{cleaned[:60]}'")
                yield cleaned
            return

        # ── LLM STREAMING PATH ────────────────────────────────────────
        # Save what we heard, then let LLM respond naturally
        self._save_from_turn(user_text, "")

        # Always stream — sentences go to TTS as soon as they are complete.
        # Tool calls (property search, confirm) are handled inline: run the
        # tool, then stream the model's follow-up answer.
        stream_msgs: list[BaseMessage] = [self._system_msg()] + self._base_messages(user_text)

        # Only send tool schemas (~700 tokens) when a tool can actually help:
        # once purpose + location are known, or for visit/confirm/farewell.
        profile = get_customer_profile(self.phone)
        use_tools = (
            intent in ("schedule_visit", "farewell", "confirm_deal")
            or bool(profile.get("intent") and profile.get("preferred_location"))
        )

        buffer = ""
        full_reply = ""

        try:
            for tool_round in range(MAX_TOOL_ROUNDS + 1):
                # Final round has no tools, so the model must answer in words
                llm = _LLM_TOOLS if use_tools and tool_round < MAX_TOOL_ROUNDS else _LLM_STREAM
                gathered = None
                async for chunk in llm.astream(stream_msgs):
                    gathered = chunk if gathered is None else gathered + chunk
                    token = chunk.content or ""
                    if not token:
                        continue
                    buffer += token
                    full_reply += token
                    complete, buffer = _flush_sentences(buffer)
                    for sentence in complete:
                        cleaned = clean_for_tts(sentence)
                        if cleaned and len(cleaned) > 3:
                            print(f"[Stream] → '{cleaned[:60]}'")
                            yield cleaned

                if gathered is None or not gathered.tool_calls:
                    break
                stream_msgs.append(gathered)
                stream_msgs.extend(await asyncio.to_thread(self._run_tools, gathered.tool_calls))

            if not full_reply.strip() and not buffer.strip():
                fallback = self._tool_fallback()
                print(f"[chat_stream] empty reply fallback → '{fallback}'")
                full_reply = fallback
                self._record_turn(user_text, fallback)
                self._save_from_turn(user_text, fallback)
                yield clean_for_tts(fallback)
                return

            if buffer.strip():
                complete, _ = _flush_sentences(buffer, force=True)
                for sentence in complete:
                    cleaned = clean_for_tts(sentence)
                    if cleaned and len(cleaned) > 3:
                        print(f"[Stream] flush → '{cleaned[:60]}'")
                        yield cleaned

        except Exception as e:
            print(f"[chat_stream error] {e}")
            if not full_reply.strip():
                yield clean_for_tts(self._tool_fallback())
            return

        if full_reply:
            self._save_from_turn(user_text, full_reply)
            self._record_turn(user_text, full_reply)

    def _run_tools(self, tool_calls: list[dict]) -> list[ToolMessage]:
        """Execute the model's tool calls and return their results."""
        results = []
        for tc in tool_calls:
            fn = _TOOL_MAP.get(tc["name"])
            args = dict(tc.get("args") or {})
            if tc["name"] == "tool_confirm_customer":
                args["phone"] = self.phone  # the model never knows the real number
            try:
                out = fn.invoke(args) if fn else json.dumps({"error": f"Unknown tool: {tc['name']}"})
            except Exception as e:
                out = json.dumps({"error": str(e)})
            results.append(ToolMessage(content=out, tool_call_id=tc["id"]))
            print(f"[Tool] {tc['name']} → {str(out)[:100]}")
        return results

    def _tool_fallback(self) -> str:
        profile = get_customer_profile(self.phone)
        name = profile.get("name") or self.customer_name or ""
        if name and not _is_valid_name(name):
            name = ""
        name_suffix = f"{name} ji" if name else "ji"
        if not profile.get("property_type"):
            return f"Bilkul {name_suffix} — aapko residential flat chahiye ya commercial? Aur kitne BHK prefer karenge?"
        if not profile.get("preferred_location"):
            return f"Aap {name_suffix} Indore mein kis area mein dekhna chahenge?"
        loc = profile.get("preferred_location", "")
        return (
            f"Theek hai {name_suffix}, maine aapki requirement note kar li hai. "
            f"Hamare senior property expert aapko jald contact karenge — "
            f"visit aur aage ki jaankari ke liye. Aapka shukriya!"
        )

    # ------------------------------------------------------------------
    # Blocking fallback
    # ------------------------------------------------------------------
    async def chat(self, user_text: str) -> str:
        parts = []
        async for s in self.chat_stream(user_text):
            parts.append(s)
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Memory helpers
    # ------------------------------------------------------------------
    def _save_from_turn(self, user_text: str, assistant_reply: str):
        """
        Extract and persist customer info from each turn.
        ORDER: budget → intent → location → property_type → name
        Budget is parsed first so "नब्बे lakh" can never be stolen as a name.
        """
        profile: dict = {"last_called": time.strftime("%Y-%m-%d")}
        existing = get_customer_profile(self.phone)

        # ── Budget FIRST (structured) ─────────────────────────────────
        # Parse before name extraction so "नब्बे lakh", "चार लाख" etc.
        # are claimed as budget and cannot be misidentified as a name.
        parsed = parse_budget(user_text)
        if parsed:
            profile["budget"] = parsed
            print(f"[Budget] parsed: {parsed}")
        _budget_found_in_text = parsed is not None

        # ── Budget "flexible / not fixed" handling ────────────────────
        # If user says budget is not fixed / open / flexible — save a sentinel
        # so the conversation advances past the budget stage.
        if not existing.get("budget") and not parsed:
            _FLEXIBLE_BUDGET = re.compile(
                r"\b(fix nahi|fixed nahi|decide nahi|pata nahi|nahi pata|"
                r"open hai|flexible|koi bhi|kuch bhi|abhi nahi|baad mein|"
                r"nahi socha|soche nahi|fixed nahin|fix nahin|"
                r"nahi socha|soch nahi|pata nahin|batana mushkil|bata nahi)\b"
                r"|budget\s*(nahi|nahin|n'?t|fix|decide)"
                r"|(?:abhi|filhaal|fardham|abhe)\s*(nahi|nahin|koi|kuch)",
                re.IGNORECASE
            )
            _FLEX_HINDI = re.compile(
                r"(फिक्स नहीं|तय नहीं|पता नहीं|कोई भी|कुछ भी|अभी नहीं|बाद में|"
                r"सोचा नहीं|नहीं सोचा|बजट नहीं|decide नहीं)",
            )
            if _FLEXIBLE_BUDGET.search(user_text) or _FLEX_HINDI.search(user_text):
                profile["budget"] = {"min_budget": None, "max_budget": None, "display": "flexible"}
                print(f"[Budget] flexible/open budget detected")

        # ── Name ─────────────────────────────────────────────────────
        # Skip name extraction entirely if this turn contains budget text —
        # prevents "नब्बे lakh" or "चार लाख" from being saved as a name.
        if not existing.get("name") and not _budget_found_in_text:
            # Pattern 1: "mera naam X hai" / "मेरा नाम X है"
            name_match = re.search(
                r"(?:mera\s+naam|मेरा\s+नाम|मेरा\s+naam|naam\s+hai|naam\s+है|नाम\s+है|my\s+name\s+is|i\s+am|i'm)\s*"
                r"([A-Za-z\u0900-\u097F]{2,20}(?:\s+[A-Za-z\u0900-\u097F]{2,20})?)"
                # Also: "haan Harsh hai", "हां, हर्ष है", "ji Rahul hoon"
                r"|^(?:haan|han|haa|ji|yes|हाँ|हां|जी)[,\s]+([A-Za-z\u0900-\u097F]{2,20})\s+(?:hai|hoon|hun|है|हूं|हूँ)\b",
                user_text,
                re.IGNORECASE | re.MULTILINE,
            )
            if name_match:
                candidate = (name_match.group(1) or name_match.group(2) or "").strip().rstrip("।.!?,;")
                candidate = re.sub(
                    r"\s*(है|हूं|हूँ|hoon|hai|he|hun|hain)$", "", candidate, flags=re.IGNORECASE
                ).strip()
                if _is_valid_name(candidate):
                    profile["name"] = candidate
            else:
                # Pattern 2: short 1-2 word reply = likely a name
                # ONLY accept if assistant just asked for the name in this turn
                _asked_for_name = any(
                    kw in assistant_reply.lower()
                    for kw in ("naam", "name", "aapka naam", "your name", "naam kya", "naam bata")
                )
                text = user_text.strip().rstrip(".!?,;।").strip()
                words = text.split()
                if _asked_for_name and 1 <= len(words) <= 2 and len(text) >= 2:
                    # Must start with a capital letter (real names are capitalised)
                    # OR be a Devanagari word of >= 3 chars (avoids "हां", "जी", "हाँ")
                    first = text[0] if text else ""
                    is_devanagari_start = not first.isascii()
                    is_capitalised_latin = first.isascii() and first.isupper()
                    # Extra guard: Devanagari names should be >= 3 chars (filters हां, जी, हाँ)
                    devanagari_long_enough = (not first.isascii()) and len(text) >= 3
                    if is_capitalised_latin or devanagari_long_enough:
                        if _is_valid_name(text):
                            profile["name"] = text

        # Special case: turn contains BOTH name and budget ("मेरा नाम X है और budget Y lakh")
        # Re-run name extraction even when budget was found, but ONLY on the name prefix
        if not existing.get("name") and _budget_found_in_text:
            name_match = re.search(
                r"(?:mera\s+naam|मेरा\s+नाम|मेरा\s+naam|naam\s+hai|naam\s+है|नाम\s+है|my\s+name\s+is)\s*"
                r"([A-Za-z\u0900-\u097F]{2,20}(?:\s+[A-Za-z\u0900-\u097F]{2,20})?)",
                user_text,
                re.IGNORECASE,
            )
            if name_match:
                candidate = name_match.group(1).strip().rstrip("।.!?,;")
                candidate = re.sub(
                    r"\s*(है|हूं|हूँ|hoon|hai|he|hun|hain)$", "", candidate, flags=re.IGNORECASE
                ).strip()
                if _is_valid_name(candidate):
                    profile["name"] = candidate

        # ── Intent ───────────────────────────────────────────────────
        if not existing.get("intent"):
            u = user_text.lower()
            # Check RENT first — "rent par lena chahta" must not fall into buy
            if (_RENT_PATTERNS.search(user_text)
                    or any(w in u for w in ("rent", "kiraya", "kiraye", "lease"))
                    or re.search(r"किराया|किराये|किराए|rent\s+पर|किराये\s+पर", user_text)):
                profile["intent"] = "rent"
            elif (any(w in u for w in ("buy", "khareedna", "kharidna", "purchase"))
                    or re.search(r"खरीदना|खरीदनी|खरीदना\s*चाहता|खरीदना\s*चाहती", user_text)):
                profile["intent"] = "buy"
            elif (any(w in u for w in ("sell", "bechna", "bechni"))
                    or re.search(r"बेचना|बेचनी|बेचना\s*चाहता", user_text)):
                profile["intent"] = "sell"
            # Legacy compat: also save as "purpose"
            if profile.get("intent"):
                profile["purpose"] = profile["intent"]

        # ── Location ─────────────────────────────────────────────────
        # Detect multiple locations: "Vijay Nagar aur Super Corridor" → save list
        if not existing.get("preferred_location"):
            # First: check if assistant just asked about location/area
            asked_location = any(
                t in assistant_reply.lower()
                for t in ("location", "kahan", "area", "jagah", "kis area", "kahan dekhna")
            )
            # Known Indore area keyword map (Romanized + Devanagari)
            _AREA_KEYWORDS = {
                # Indore areas
                "nipania": "Nipania", "निपानिया": "Nipania",
                "vijay nagar": "Vijay Nagar", "vijaynagar": "Vijay Nagar",
                "super corridor": "Super Corridor", "supercorridor": "Super Corridor",
                "khandwa": "Khandwa Road", "khandwa road": "Khandwa Road",
                "kanadia": "Kanadia Bypass", "kanadiya": "Kanadia Bypass",
                "bypass": "Bypass",
                "scheme 140": "Scheme 140", "scheme140": "Scheme 140",
                "scheme 54": "Scheme 54", "scheme54": "Scheme 54",
                "bicholi": "Bicholi", "ring road": "Ring Road",
                "ujjain road": "Ujjain Road", "rajendra nagar": "Rajendra Nagar",
                "mahalakshmi": "Mahalakshmi Nagar", "tilak nagar": "Tilak Nagar",
                "palasia": "Palasia",
                "bhawarkuan": "Bhawarkuan", "bhawarkua": "Bhawarkuan",
                "bhanwarkua": "Bhawarkuan", "bhanwarkuan": "Bhawarkuan",
                "bhawarkua naka": "Bhawarkuan",
                "rau": "Rau", "annapurna": "Annapurna Road",
                "paliya": "Paliya Naka", "lig": "LIG Main Square",
                "omaxe": "Bypass Omaxe",
                "ab road": "AB Road", "lasudia": "Lasudia",
                "navda": "Navda Panth", "navda panth": "Navda Panth",
                "mhow": "Mhow", "pithampur": "Rau Pithampur Road",
                "aerodrome": "Aerodrome Road", "airport": "Airport Road",
                "kalindi": "Kalindi Gold", "puwarda": "Super Corridor",
                "iim": "Super Corridor", "iit": "Super Corridor",
                "medical hub": "Super Corridor",
                "hatod": "Hatod", "sanwer": "Sanwer Road",
                "sukhliya": "Sukhliya", "tejaji nagar": "Tejaji Nagar",
                "tejaji": "Tejaji Nagar", "mangaliya": "Mangaliya",
                "limbodi": "Limbodi", "depalpur": "Depalpur",
                "mundla": "Mundla Nayta", "nayta": "Mundla Nayta",
                "bijalpur": "Bijalpur", "khudel": "Khudel",
                "simrol": "Simrol", "khajrana": "Khajrana",
                "sudama nagar": "Sudama Nagar", "sudama": "Sudama Nagar",
                "banganga": "Banganga", "gumasta": "Gumasta Nagar",
                "dhanwantri": "Dhanwantri Nagar", "geeta bhawan": "Geeta Bhawan",
                "bijalpur": "Bijalpur", "kesar bagh": "Kesar Bagh",
                "MR 10": "MR-10", "mr10": "MR-10", "mr 10": "MR-10",
                "saket": "Saket Nagar",
                # Bhopal areas
                "bhopal": "Bhopal", "kolar": "Kolar Road",
                "mandideep": "Mandideep", "arera": "Arera Colony",
                "habibganj": "Habibganj", "karond": "Karond",
                "bairagarh": "Bairagarh", "bhanpur": "Bhanpur",
                "shahpura": "Shahpura", "trilanga": "Trilanga",
                "misrod": "Misrod", "ayodhya nagar": "Ayodhya Nagar",
                # Cities
                "indore": "Indore", "ujjain": "Ujjain",
                "dewas": "Dewas", "ratlam": "Ratlam",
                "jabalpur": "Jabalpur", "gwalior": "Gwalior",
                "sagar": "Sagar", "satna": "Satna", "rewa": "Rewa",
                "mandsaur": "Mandsaur", "neemuch": "Neemuch",
                "khargone": "Khargone", "dhar": "Dhar",
                "hoshangabad": "Hoshangabad", "sehore": "Sehore",
            }
            u_lower = user_text.lower()
            u_orig  = user_text          # for Devanagari keywords
            matched_area = None
            # Check area keywords (longest match first)
            for kw in sorted(_AREA_KEYWORDS.keys(), key=len, reverse=True):
                if kw in u_lower or kw in u_orig:
                    matched_area = _AREA_KEYWORDS[kw]
                    break
            if matched_area:
                # Check if user mentioned a second location ("aur", "ya", "or", "aur bhi")
                _CONJUNCTIONS = re.compile(
                    r"\b(aur|ya|or|aur bhi|aur ek|और|या)\b", re.IGNORECASE
                )
                if _CONJUNCTIONS.search(user_text):
                    # Try to find a second area keyword after the conjunction
                    second_area = None
                    for kw2 in sorted(_AREA_KEYWORDS.keys(), key=len, reverse=True):
                        if kw2 != kw and (kw2 in u_lower or kw2 in u_orig):
                            second_area = _AREA_KEYWORDS[kw2]
                            break
                    if second_area:
                        # Save as comma-separated string — agent will search both
                        profile["preferred_location"] = f"{matched_area}, {second_area}"
                    else:
                        profile["preferred_location"] = matched_area
                else:
                    profile["preferred_location"] = matched_area
            elif asked_location:
                # Treat the whole reply as location if no specific keyword found
                candidate = user_text.strip().rstrip(".!?,;।").strip()
                # Reject if the candidate contains intent/action words — it's not a location
                _INTENT_WORDS = re.compile(
                    r"\b(bechna|kharidna|khareedna|sell|buy|rent|kiraya|chahta|chahti|chahte|"
                    r"hoon|haan|nahi|budget|lakh|crore|commercial|residential|bhk|property|"
                    r"lena|dena|purchase)\b"
                    # Devanagari intent/action words
                    r"|खरीदना|खरीदनी|ख़रीदना|बेचना|बेचनी|किराया|चाहता|चाहती|चाहते|"
                    r"property|प्रॉपर्टी|लेना|देना|हूं|हूँ|नहीं|बजट|लाख|करोड़",
                    re.IGNORECASE,
                )
                if (
                    1 <= len(candidate.split()) <= 5
                    and not any(c.isdigit() for c in candidate)
                    and candidate.lower() not in _NAME_BLOCKLIST
                    and not _INTENT_WORDS.search(candidate)
                ):
                    profile["preferred_location"] = candidate
            else:
                u = user_text.lower()
                for city in (
                    "indore", "bhopal", "ujjain", "dewas", "ratlam",
                    "jabalpur", "gwalior",
                ):
                    if city in u:
                        profile["preferred_location"] = city.title()
                        break

        # ── Property type ─────────────────────────────────────────────
        if not existing.get("property_type"):
            u = user_text.lower()
            # ── BHK RANGE: "दो तीन BHK", "do ya teen BHK", "2-3 BHK" ──
            _HINDI_NUM = {
                "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5,
                "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 4, "पांच": 5,
            }
            range_bhk = re.search(
                r"\b(ek|do|teen|char|paanch|एक|दो|तीन|चार|पाँच|पांच|\d)"
                r"(?:\s*(?:se|ya|aur|to|[-–])\s*)"
                r"(ek|do|teen|char|paanch|एक|दो|तीन|चार|पाँच|पांच|\d)"
                r"\s*(?:bhk|BHK|बीएचके)\b",
                user_text, re.IGNORECASE,
            )
            # Also catch: "do teen BHK" (no separator — two Hindi numbers before BHK)
            range_nospace = re.search(
                r"\b(ek|do|teen|char|paanch|एक|दो|तीन|चार|पाँच|पांच)"
                r"\s+(ek|do|teen|char|paanch|एक|दो|तीन|चार|पाँच|पांच)"
                r"\s*(?:bhk|BHK|बीएचके)\b",
                user_text, re.IGNORECASE,
            )
            if range_bhk:
                g1 = range_bhk.group(1).lower()
                g2 = range_bhk.group(2).lower()
                n1 = _HINDI_NUM.get(g1, int(g1) if g1.isdigit() else None)
                n2 = _HINDI_NUM.get(g2, int(g2) if g2.isdigit() else None)
                if n1 and n2:
                    lo, hi = min(n1, n2), max(n1, n2)
                    profile["property_type"] = f"{lo}-{hi} BHK"
            elif range_nospace:
                g1 = range_nospace.group(1).lower()
                g2 = range_nospace.group(2).lower()
                n1 = _HINDI_NUM.get(g1)
                n2 = _HINDI_NUM.get(g2)
                if n1 and n2:
                    lo, hi = min(n1, n2), max(n1, n2)
                    profile["property_type"] = f"{lo}-{hi} BHK"
            else:
                bhk_match = re.search(r"\b(\d)\s*bhk\b", u)
                if bhk_match:
                    profile["property_type"] = f"{bhk_match.group(1)} BHK"
                else:
                    # Hindi/Devanagari BHK: "do BHK", "दो BHK", "teen BHK" etc.
                    _HINDI_BHK = {
                        "ek": "1", "do": "2", "teen": "3", "char": "4", "paanch": "5",
                        "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पाँच": "5", "पांच": "5",
                    }
                    hindi_bhk = re.search(
                        r"\b(ek|do|teen|char|paanch|एक|दो|तीन|चार|पाँच|पांच)\s*(?:bhk|BHK|बीएचके)\b",
                        user_text, re.IGNORECASE
                    )
                    if hindi_bhk:
                        num = _HINDI_BHK.get(hindi_bhk.group(1).lower(), hindi_bhk.group(1))
                        profile["property_type"] = f"{num} BHK"
                    elif "commercial" in u:
                        profile["property_type"] = "commercial"
                    elif any(w in u for w in ("plot", "land", "zameen")):
                        profile["property_type"] = "plot"
                    elif any(w in u for w in ("flat", "apartment", "residential")):
                        profile["property_type"] = "residential"

        # ── Stage tracking ────────────────────────────────────────────
        p_merged = {**existing, **profile}
        if p_merged.get("stage") == "confirmed":
            profile["stage"] = "confirmed"  # never downgrade a confirmed customer
        elif p_merged.get("property_type"):
            profile["stage"] = "complete"
            # Auto-confirm customer when all 5 fields are collected
            if (
                p_merged.get("name") and p_merged.get("intent")
                and p_merged.get("preferred_location") and p_merged.get("budget")
                and existing.get("stage") != "confirmed"
                and existing.get("stage") != "complete"
            ):
                try:
                    from estate_functions import save_confirmed_customer as _confirm
                    budget_display = (
                        p_merged["budget"].get("display", str(p_merged["budget"]))
                        if isinstance(p_merged["budget"], dict)
                        else str(p_merged["budget"])
                    )
                    _confirm(
                        phone=self.phone,
                        name=p_merged.get("name", ""),
                        intent=p_merged.get("intent", ""),
                        location=p_merged.get("preferred_location", ""),
                        budget=budget_display,
                        property_type=p_merged.get("property_type", ""),
                    )
                    print(f"[Confirm] Auto-confirmed customer {self.phone}")
                except Exception as e:
                    print(f"[Confirm] Auto-confirm failed: {e}")
        elif p_merged.get("budget"):
            # Budget is set (including flexible) — advance to property_type stage
            profile["stage"] = "property_type"
        elif p_merged.get("preferred_location"):
            profile["stage"] = "budget"
        elif p_merged.get("intent") or p_merged.get("purpose"):
            profile["stage"] = "location"
        elif p_merged.get("name"):
            profile["stage"] = "intent"
        else:
            profile["stage"] = "name"

        meaningful = {k: v for k, v in profile.items() if k != "last_called" and v}
        if meaningful or "last_called" in profile:
            save_customer_profile(self.phone, profile)
            if meaningful:
                print(f"[Memory] Saved for {self.phone}: {meaningful}")

    def _record_turn(self, user_text: str, assistant_reply: str):
        """Append turn to in-call history for LLM context."""
        self._call_history.append(HumanMessage(content=user_text))
        self._call_history.append(AIMessage(content=assistant_reply))
        # Keep last 10 turns (20 messages)
        if len(self._call_history) > 20:
            self._call_history = self._call_history[-20:]