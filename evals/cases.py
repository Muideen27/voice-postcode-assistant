"""Held-out eval cases. Never copy one of these into prompts.INTENT_FEW_SHOT (tests/test_llm.py checks).

Intent: 10 per language, each with noisy ASR-style transcripts (no accents, run-on, spelled by sound).
Explain: 3 per language.
"""

INTENT_CASES: dict[str, list[tuple[str, str]]] = {
    "en": [
        ("Hello, can you tell me my postcode? I stay in Surulere.", "get_my_postcode"),
        ("i wan know my post code for my house for yaba", "get_my_postcode"),
        ("Is OG-02-B11-AA-07 a real postcode?", "validate_postcode"),
        ("how can i know if the postcode they gave me is correct", "validate_postcode"),
        ("What is the meaning of the numbers in a postcode?", "explain_postcode"),
        ("wat is d district part for postcode mean", "explain_postcode"),
        ("Good evening", "greeting"),
        ("thank you so much", "greeting"),
        ("What time does the bank open?", "other"),
        ("uh my postcode is la eleven a twelve g n zero one is it correct", "validate_postcode"),
    ],
    "yo": [
        ("Ẹ jọ̀wọ́, kí ni pósíkòdì ibi tí mo ń gbé? Mo wà ní Ìbàdàn.", "get_my_postcode"),
        ("mo fe mo koodu ile mi ni ikorodu", "get_my_postcode"),
        ("Ṣé LA-11-A12-GN-01 jẹ́ pósíkòdì tó tọ̀nà?", "validate_postcode"),
        ("báwo ni mo ṣe lè mọ̀ bóyá pósíkòdì mi tọ̀nà", "validate_postcode"),
        ("Kí ni apá kọ̀ọ̀kan nínú pósíkòdì túmọ̀ sí?", "explain_postcode"),
        ("ki ni itumo posikodi tuntun yi", "explain_postcode"),
        ("Ẹ káàsán o", "greeting"),
        ("e se pupo", "greeting"),
        ("Níbo ni mo ti lè ra búrẹ́dì?", "other"),
        ("ejo mo fe mo posikodi mi ni ile wa ni oshodi", "get_my_postcode"),
    ],
    "ha": [
        ("Don Allah, menene postcode na gidana? Ina zaune a Kaduna.", "get_my_postcode"),
        ("ina son sanin postcode na gida na zaria", "get_my_postcode"),
        ("KN-31-F82-WJ-80 postcode ce ingantacciya?", "validate_postcode"),
        ("ta yaya zan san ko postcode dina daidai ne", "validate_postcode"),
        ("Menene ma'anar haruffan farko a cikin postcode?", "explain_postcode"),
        ("mene ne ma ana sassan lamba gidan waya", "explain_postcode"),
        ("Ina kwana", "greeting"),
        ("na gode sosai", "greeting"),
        ("Yaushe za a yi ruwan sama?", "other"),
        ("assalamu alaikum ina son lambar gidan waya ta a kano", "get_my_postcode"),
    ],
    "ig": [
        ("Biko, gịnị bụ postcode ebe m bi? Ana m ebi n'Owerri.", "get_my_postcode"),
        ("achoro m ima postcode ulo m na nsukka", "get_my_postcode"),
        ("EN-04-C21-KD-15 ọ bụ postcode ziri ezi?", "validate_postcode"),
        ("kedu ka m ga-esi mara ma postcode m ziri ezi", "validate_postcode"),
        ("Gịnị ka akụkụ ọ bụla nke postcode pụtara?", "explain_postcode"),
        ("gini bu postcode ohuru a", "explain_postcode"),
        ("Ụtụtụ ọma", "greeting"),
        ("daalu nke ukwu", "greeting"),
        ("Ebee ka m ga-azụta akwụkwọ nri?", "other"),
        ("nno biko enyere m aka ichota postcode m", "get_my_postcode"),
    ],
}

EXPLAIN_CASES: dict[str, list[str]] = {
    "en": [
        "What does each part of a postcode mean?",
        "Can you tell me my postcode if I tell you my street name?",
        "Since when do we have these new postcodes?",
    ],
    "yo": [
        "Kí ni apá kọ̀ọ̀kan pósíkòdì túmọ̀ sí?",
        "Ṣé ẹ lè fún mi ní pósíkòdì mi tí mo bá sọ orúkọ òpópónà mi?",
        "Ìgbà wo ni pósíkòdì tuntun yìí bẹ̀rẹ̀?",
    ],
    "ha": [
        "Menene ma'anar kowane sashe na postcode?",
        "Za ku iya ba ni postcode dina idan na faɗi sunan titina?",
        "Tun yaushe aka fara amfani da sabbin postcode?",
    ],
    "ig": [
        "Gịnị ka akụkụ ọ bụla nke postcode pụtara?",
        "Ị nwere ike inye m postcode m ma m gwa gị aha okporo ụzọ m?",
        "Kemgbe ole ka postcode ọhụrụ ndị a malitere?",
    ],
}

# FAQ routing (EXPLAIN_MODE=faq): the 12 explain questions above plus 8 more, 5 per language, with the
# expected faq_id. Scored by outcome: get_mine also counts as correct when the LLM says get_my_postcode
# (same screen: ask for location), and check_one when it says validate_postcode (same screen: ask for code).
FAQ_CASES: dict[str, list[tuple[str, str]]] = {
    "en": [
        (EXPLAIN_CASES["en"][0], "parts"),
        (EXPLAIN_CASES["en"][1], "place_name_no"),
        (EXPLAIN_CASES["en"][2], "since_when"),
        ("Is my information kept when I use this?", "privacy"),
        ("What exactly is a postcode?", "what_is"),
    ],
    "yo": [
        (EXPLAIN_CASES["yo"][0], "parts"),
        (EXPLAIN_CASES["yo"][1], "place_name_no"),
        (EXPLAIN_CASES["yo"][2], "since_when"),
        ("Kí ni pósíkòdì gan-an?", "what_is"),
        ("Báwo ni mo ṣe lè ṣàyẹ̀wò bóyá pósíkòdì kan jẹ́ òótọ́?", "check_one"),
    ],
    "ha": [
        (EXPLAIN_CASES["ha"][0], "parts"),
        (EXPLAIN_CASES["ha"][1], "place_name_no"),
        (EXPLAIN_CASES["ha"][2], "since_when"),
        ("Wa ya ƙirƙiro wannan sabis ɗin?", "who_built"),
        ("Ta yaya zan samu postcode ta?", "get_mine"),
    ],
    "ig": [
        (EXPLAIN_CASES["ig"][0], "parts"),
        (EXPLAIN_CASES["ig"][1], "place_name_no"),
        (EXPLAIN_CASES["ig"][2], "since_when"),
        ("Ị na-edebe ebe m nọ?", "privacy"),
        ("Gịnị bụ postcode?", "what_is"),
    ],
}
FAQ_EQUIVALENT_INTENTS = {"get_mine": "get_my_postcode", "check_one": "validate_postcode"}

# Street / place-name questions (faq place_name_no): the 4 FAQ_CASES that missed on 8 Oct plus 8 new ones.
# Expected route: explain_postcode + place_name_no (via the LLM, or the street/name rule in resolve_route).
PLACE_NAME_CASES: dict[str, list[str]] = {
    "en": [
        EXPLAIN_CASES["en"][1],
        "My street is Adeola Odeku, what is my postcode?",
        "what is the postcode for 12 Bode Thomas road",
    ],
    "yo": [
        EXPLAIN_CASES["yo"][1],
        "Orúkọ òpópónà mi ni Allen, kí ni pósíkòdì mi?",
        "ṣe o le wa posikodi mi pelu oruko adugbo mi",
    ],
    "ha": [
        EXPLAIN_CASES["ha"][1],
        "Titina shi ne Zoo Road, menene postcode dina?",
        "sunan unguwata sabon gari ina postcode dina",
    ],
    "ig": [
        EXPLAIN_CASES["ig"][1],
        "Aha okporo ụzọ m bụ Ogui Road, kedu postcode m?",
        "enwere m ike inye gi aha obodo m ka i choputa postcode m",
    ],
}
