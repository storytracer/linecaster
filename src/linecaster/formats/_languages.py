"""Language and script values of PAGE-XML and the codes behind them: PAGE's language names (``LanguageSimpleType``,
English names) <-> BCP 47 tags, PAGE's script values (``ScriptSimpleType``, ``"Latn - Latin"``) <-> ISO 15924 codes,
and the ISO 639 two-letter code of a three-letter one (BCP 47 takes the two-letter code where ISO 639-1 has one, so
``eng``, ``deu`` and ``ger`` read as ``en`` and ``de``).

The tables were generated on 2026-11-15 from the enumerations of the PAGE 2019-07-15 schema
(``tests/schemas/pagecontent-2019-07-15.xsd``) and the ISO 639-3 code table (``iso-639-3.tab``): a PAGE name
matched by its ISO 639-3 reference name gives the ISO 639-1 code where there is one, else the ISO 639-3 code. The
names ISO 639-3 names otherwise were mapped by hand: Abkhaz ab, Bihari bh (ISO 639-1's collective code), Cambodian
km, Cantonese yue, Divehi dv, Fula ff, Gaelic gd (Scottish Gaelic), Greek el (Modern Greek), Guaraní gn, Interlingua
ia, Inuktitut iu, Kirundi rn, Kwanyama kj, Kyrgyz ky, Limburgish li, Malay ms, Māori mi, Nepali ne, Nuosu ii, Occitan
oc, Ojibwe oj, Old Church Slavonic cu, Oriya or, Ossetian os, Pāli pi, Pashto ps, Punjabi pa, Slovene sl, Swahili sw,
Tonga to (Tonga Islands). PAGE's ``other`` names no language and maps to none. Two names share a code (Cambodian and
Khmer km, Panjabi and Punjabi pa); a code is written as the later name.
"""
from __future__ import annotations

from ..data.writing import is_script, language_tag

#: PAGE language name -> BCP 47 tag
PAGE_LANGUAGES = {
    "Abkhaz": "ab", "Afar": "aa", "Afrikaans": "af", "Akan": "ak", "Albanian": "sq", "Amharic": "am",
    "Arabic": "ar", "Aragonese": "an", "Armenian": "hy", "Assamese": "as", "Avaric": "av", "Avestan": "ae",
    "Aymara": "ay", "Azerbaijani": "az", "Bambara": "bm", "Bashkir": "ba", "Basque": "eu", "Belarusian": "be",
    "Bengali": "bn", "Bihari": "bh", "Bislama": "bi", "Bosnian": "bs", "Breton": "br", "Bulgarian": "bg",
    "Burmese": "my", "Cambodian": "km", "Cantonese": "yue", "Catalan": "ca", "Chamorro": "ch", "Chechen": "ce",
    "Chichewa": "ny", "Chinese": "zh", "Chuvash": "cv", "Cornish": "kw", "Corsican": "co", "Cree": "cr",
    "Croatian": "hr", "Czech": "cs", "Danish": "da", "Divehi": "dv", "Dutch": "nl", "Dzongkha": "dz",
    "English": "en", "Esperanto": "eo", "Estonian": "et", "Ewe": "ee", "Faroese": "fo", "Fijian": "fj",
    "Finnish": "fi", "French": "fr", "Fula": "ff", "Gaelic": "gd", "Galician": "gl", "Ganda": "lg",
    "Georgian": "ka", "German": "de", "Greek": "el", "Guaraní": "gn", "Gujarati": "gu", "Haitian": "ht",
    "Hausa": "ha", "Hebrew": "he", "Herero": "hz", "Hindi": "hi", "Hiri Motu": "ho", "Hungarian": "hu",
    "Icelandic": "is", "Ido": "io", "Igbo": "ig", "Indonesian": "id", "Interlingua": "ia", "Interlingue": "ie",
    "Inuktitut": "iu", "Inupiaq": "ik", "Irish": "ga", "Italian": "it", "Japanese": "ja", "Javanese": "jv",
    "Kalaallisut": "kl", "Kannada": "kn", "Kanuri": "kr", "Kashmiri": "ks", "Kazakh": "kk", "Khmer": "km",
    "Kikuyu": "ki", "Kinyarwanda": "rw", "Kirundi": "rn", "Komi": "kv", "Kongo": "kg", "Korean": "ko",
    "Kurdish": "ku", "Kwanyama": "kj", "Kyrgyz": "ky", "Lao": "lo", "Latin": "la", "Latvian": "lv",
    "Limburgish": "li", "Lingala": "ln", "Lithuanian": "lt", "Luba-Katanga": "lu", "Luxembourgish": "lb",
    "Macedonian": "mk", "Malagasy": "mg", "Malay": "ms", "Malayalam": "ml", "Maltese": "mt", "Manx": "gv",
    "Māori": "mi", "Marathi": "mr", "Marshallese": "mh", "Mongolian": "mn", "Nauru": "na", "Navajo": "nv",
    "Ndonga": "ng", "Nepali": "ne", "North Ndebele": "nd", "Northern Sami": "se", "Norwegian": "no",
    "Norwegian Bokmål": "nb", "Norwegian Nynorsk": "nn", "Nuosu": "ii", "Occitan": "oc", "Ojibwe": "oj",
    "Old Church Slavonic": "cu", "Oriya": "or", "Oromo": "om", "Ossetian": "os", "Pāli": "pi", "Panjabi": "pa",
    "Pashto": "ps", "Persian": "fa", "Polish": "pl", "Portuguese": "pt", "Punjabi": "pa", "Quechua": "qu",
    "Romanian": "ro", "Romansh": "rm", "Russian": "ru", "Samoan": "sm", "Sango": "sg", "Sanskrit": "sa",
    "Sardinian": "sc", "Serbian": "sr", "Shona": "sn", "Sindhi": "sd", "Sinhala": "si", "Slovak": "sk",
    "Slovene": "sl", "Somali": "so", "South Ndebele": "nr", "Southern Sotho": "st", "Spanish": "es",
    "Sundanese": "su", "Swahili": "sw", "Swati": "ss", "Swedish": "sv", "Tagalog": "tl", "Tahitian": "ty",
    "Tajik": "tg", "Tamil": "ta", "Tatar": "tt", "Telugu": "te", "Thai": "th", "Tibetan": "bo", "Tigrinya": "ti",
    "Tonga": "to", "Tsonga": "ts", "Tswana": "tn", "Turkish": "tr", "Turkmen": "tk", "Twi": "tw", "Uighur": "ug",
    "Ukrainian": "uk", "Urdu": "ur", "Uzbek": "uz", "Venda": "ve", "Vietnamese": "vi", "Volapük": "vo",
    "Walloon": "wa", "Welsh": "cy", "Western Frisian": "fy", "Wolof": "wo", "Xhosa": "xh", "Yiddish": "yi",
    "Yoruba": "yo", "Zhuang": "za", "Zulu": "zu",
}

#: PAGE script values (each an ISO 15924 code and its English name)
PAGE_SCRIPTS = (
    "Adlm - Adlam", "Afak - Afaka", "Aghb - Caucasian Albanian", "Ahom - Ahom, Tai Ahom", "Arab - Arabic",
    "Aran - Arabic (Nastaliq variant)", "Armi - Imperial Aramaic", "Armn - Armenian", "Avst - Avestan",
    "Bali - Balinese", "Bamu - Bamum", "Bass - Bassa Vah", "Batk - Batak", "Beng - Bengali", "Bhks - Bhaiksuki",
    "Blis - Blissymbols", "Bopo - Bopomofo", "Brah - Brahmi", "Brai - Braille", "Bugi - Buginese", "Buhd - Buhid",
    "Cakm - Chakma", "Cans - Unified Canadian Aboriginal Syllabics", "Cari - Carian", "Cham - Cham",
    "Cher - Cherokee", "Cirt - Cirth", "Copt - Coptic", "Cprt - Cypriot", "Cyrl - Cyrillic",
    "Cyrs - Cyrillic (Old Church Slavonic variant)", "Deva - Devanagari (Nagari)", "Dsrt - Deseret (Mormon)",
    "Dupl - Duployan shorthand, Duployan stenography", "Egyd - Egyptian demotic", "Egyh - Egyptian hieratic",
    "Egyp - Egyptian hieroglyphs", "Elba - Elbasan", "Ethi - Ethiopic",
    "Geok - Khutsuri (Asomtavruli and Nuskhuri)", "Geor - Georgian (Mkhedruli)", "Glag - Glagolitic",
    "Goth - Gothic", "Gran - Grantha", "Grek - Greek", "Gujr - Gujarati", "Guru - Gurmukhi",
    "Hanb - Han with Bopomofo", "Hang - Hangul", "Hani - Han (Hanzi, Kanji, Hanja)", "Hano - Hanunoo (Hanunóo)",
    "Hans - Han (Simplified variant)", "Hant - Han (Traditional variant)", "Hatr - Hatran", "Hebr - Hebrew",
    "Hira - Hiragana", "Hluw - Anatolian Hieroglyphs", "Hmng - Pahawh Hmong", "Hrkt - Japanese syllabaries",
    "Hung - Old Hungarian (Hungarian Runic)", "Inds - Indus (Harappan)", "Ital - Old Italic (Etruscan, Oscan etc.)",
    "Jamo - Jamo", "Java - Javanese", "Jpan - Japanese", "Jurc - Jurchen", "Kali - Kayah Li", "Kana - Katakana",
    "Khar - Kharoshthi", "Khmr - Khmer", "Khoj - Khojki", "Kitl - Khitan large script",
    "Kits - Khitan small script", "Knda - Kannada", "Kore - Korean (alias for Hangul + Han)", "Kpel - Kpelle",
    "Kthi - Kaithi", "Lana - Tai Tham (Lanna)", "Laoo - Lao", "Latf - Latin (Fraktur variant)",
    "Latg - Latin (Gaelic variant)", "Latn - Latin", "Leke - Leke", "Lepc - Lepcha (Róng)", "Limb - Limbu",
    "Lina - Linear A", "Linb - Linear B", "Lisu - Lisu (Fraser)", "Loma - Loma", "Lyci - Lycian", "Lydi - Lydian",
    "Mahj - Mahajani", "Mand - Mandaic, Mandaean", "Mani - Manichaean", "Marc - Marchen",
    "Maya - Mayan hieroglyphs", "Mend - Mende Kikakui", "Merc - Meroitic Cursive", "Mero - Meroitic Hieroglyphs",
    "Mlym - Malayalam", "Modi - Modi, Moḍī", "Mong - Mongolian", "Moon - Moon (Moon code, Moon script, Moon type)",
    "Mroo - Mro, Mru", "Mtei - Meitei Mayek (Meithei, Meetei)", "Mult - Multani", "Mymr - Myanmar (Burmese)",
    "Narb - Old North Arabian (Ancient North Arabian)", "Nbat - Nabataean", "Newa - Newa, Newar, Newari",
    "Nkgb - Nakhi Geba", "Nkoo - N’Ko", "Nshu - Nüshu", "Ogam - Ogham", "Olck - Ol Chiki (Ol Cemet’, Ol, Santali)",
    "Orkh - Old Turkic, Orkhon Runic", "Orya - Oriya", "Osge - Osage", "Osma - Osmanya", "Palm - Palmyrene",
    "Pauc - Pau Cin Hau", "Perm - Old Permic", "Phag - Phags-pa", "Phli - Inscriptional Pahlavi",
    "Phlp - Psalter Pahlavi", "Phlv - Book Pahlavi", "Phnx - Phoenician", "Piqd - Klingon (KLI pIqaD)",
    "Plrd - Miao (Pollard)", "Prti - Inscriptional Parthian", "Rjng - Rejang (Redjang, Kaganga)",
    "Roro - Rongorongo", "Runr - Runic", "Samr - Samaritan", "Sara - Sarati", "Sarb - Old South Arabian",
    "Saur - Saurashtra", "Sgnw - SignWriting", "Shaw - Shavian (Shaw)", "Shrd - Sharada, Śāradā", "Sidd - Siddham",
    "Sind - Khudawadi, Sindhi", "Sinh - Sinhala", "Sora - Sora Sompeng", "Sund - Sundanese", "Sylo - Syloti Nagri",
    "Syrc - Syriac", "Syre - Syriac (Estrangelo variant)", "Syrj - Syriac (Western variant)",
    "Syrn - Syriac (Eastern variant)", "Tagb - Tagbanwa", "Takr - Takri", "Tale - Tai Le", "Talu - New Tai Lue",
    "Taml - Tamil", "Tang - Tangut", "Tavt - Tai Viet", "Telu - Telugu", "Teng - Tengwar",
    "Tfng - Tifinagh (Berber)", "Tglg - Tagalog (Baybayin, Alibata)", "Thaa - Thaana", "Thai - Thai",
    "Tibt - Tibetan", "Tirh - Tirhuta", "Ugar - Ugaritic", "Vaii - Vai", "Visp - Visible Speech",
    "Wara - Warang Citi (Varang Kshiti)", "Wole - Woleai", "Xpeo - Old Persian",
    "Xsux - Cuneiform, Sumero-Akkadian", "Yiii - Yi", "Zinh - Code for inherited script",
    "Zmth - Mathematical notation", "Zsye - Symbols (Emoji variant)", "Zsym - Symbols",
    "Zxxx - Code for unwritten documents", "Zyyy - Code for undetermined script", "Zzzz - Code for uncoded script",
)

#: ISO 639-2 (bibliographic and terminological) and ISO 639-3 code -> the ISO 639-1 code of the same language
TWO_LETTER = {
    "aar": "aa", "abk": "ab", "afr": "af", "aka": "ak", "alb": "sq", "amh": "am", "ara": "ar", "arg": "an",
    "arm": "hy", "asm": "as", "ava": "av", "ave": "ae", "aym": "ay", "aze": "az", "bak": "ba", "bam": "bm",
    "baq": "eu", "bel": "be", "ben": "bn", "bis": "bi", "bod": "bo", "bos": "bs", "bre": "br", "bul": "bg",
    "bur": "my", "cat": "ca", "ces": "cs", "cha": "ch", "che": "ce", "chi": "zh", "chu": "cu", "chv": "cv",
    "cor": "kw", "cos": "co", "cre": "cr", "cym": "cy", "cze": "cs", "dan": "da", "deu": "de", "div": "dv",
    "dut": "nl", "dzo": "dz", "ell": "el", "eng": "en", "epo": "eo", "est": "et", "eus": "eu", "ewe": "ee",
    "fao": "fo", "fas": "fa", "fij": "fj", "fin": "fi", "fra": "fr", "fre": "fr", "fry": "fy", "ful": "ff",
    "geo": "ka", "ger": "de", "gla": "gd", "gle": "ga", "glg": "gl", "glv": "gv", "gre": "el", "grn": "gn",
    "guj": "gu", "hat": "ht", "hau": "ha", "hbs": "sh", "heb": "he", "her": "hz", "hin": "hi", "hmo": "ho",
    "hrv": "hr", "hun": "hu", "hye": "hy", "ibo": "ig", "ice": "is", "ido": "io", "iii": "ii", "iku": "iu",
    "ile": "ie", "ina": "ia", "ind": "id", "ipk": "ik", "isl": "is", "ita": "it", "jav": "jv", "jpn": "ja",
    "kal": "kl", "kan": "kn", "kas": "ks", "kat": "ka", "kau": "kr", "kaz": "kk", "khm": "km", "kik": "ki",
    "kin": "rw", "kir": "ky", "kom": "kv", "kon": "kg", "kor": "ko", "kua": "kj", "kur": "ku", "lao": "lo",
    "lat": "la", "lav": "lv", "lim": "li", "lin": "ln", "lit": "lt", "ltz": "lb", "lub": "lu", "lug": "lg",
    "mac": "mk", "mah": "mh", "mal": "ml", "mao": "mi", "mar": "mr", "may": "ms", "mkd": "mk", "mlg": "mg",
    "mlt": "mt", "mon": "mn", "mri": "mi", "msa": "ms", "mya": "my", "nau": "na", "nav": "nv", "nbl": "nr",
    "nde": "nd", "ndo": "ng", "nep": "ne", "nld": "nl", "nno": "nn", "nob": "nb", "nor": "no", "nya": "ny",
    "oci": "oc", "oji": "oj", "ori": "or", "orm": "om", "oss": "os", "pan": "pa", "per": "fa", "pli": "pi",
    "pol": "pl", "por": "pt", "pus": "ps", "que": "qu", "roh": "rm", "ron": "ro", "rum": "ro", "run": "rn",
    "rus": "ru", "sag": "sg", "san": "sa", "sin": "si", "slk": "sk", "slo": "sk", "slv": "sl", "sme": "se",
    "smo": "sm", "sna": "sn", "snd": "sd", "som": "so", "sot": "st", "spa": "es", "sqi": "sq", "srd": "sc",
    "srp": "sr", "ssw": "ss", "sun": "su", "swa": "sw", "swe": "sv", "tah": "ty", "tam": "ta", "tat": "tt",
    "tel": "te", "tgk": "tg", "tgl": "tl", "tha": "th", "tib": "bo", "tir": "ti", "ton": "to", "tsn": "tn",
    "tso": "ts", "tuk": "tk", "tur": "tr", "twi": "tw", "uig": "ug", "ukr": "uk", "urd": "ur", "uzb": "uz",
    "ven": "ve", "vie": "vi", "vol": "vo", "wel": "cy", "wln": "wa", "wol": "wo", "xho": "xh", "yid": "yi",
    "yor": "yo", "zha": "za", "zho": "zh", "zul": "zu",
}

#: BCP 47 tag -> PAGE language name
PAGE_LANGUAGE_NAMES = {tag: name for name, tag in PAGE_LANGUAGES.items()}
#: PAGE script value -> ISO 15924 code, and back
PAGE_SCRIPT_CODES = {value: value[:4] for value in PAGE_SCRIPTS}
PAGE_SCRIPT_VALUES = {code: value for value, code in PAGE_SCRIPT_CODES.items()}


def canonical(value: str | None) -> str | None:
    """A source's language value as a BCP 47 tag (``linecaster.data.writing.language_tag``), its language subtag the
    ISO 639-1 code where the source gave a three-letter code with one (``eng`` -> ``en``, ``ger-DE`` -> ``de-DE``);
    ``None`` for a value that is none."""
    tag = language_tag(value)
    if tag is None:
        return None
    first, sep, rest = tag.partition("-")
    two = TWO_LETTER.get(first.lower())
    return two + sep + rest if two else tag


def from_page_language(name: str | None) -> str | None:
    """The BCP 47 tag of a PAGE language name (``German`` -> ``de``); ``None`` for ``other`` or an unknown name."""
    return PAGE_LANGUAGES.get((name or "").strip())


def page_language(tag: str | None) -> str | None:
    """The PAGE language name of a BCP 47 tag's language (``de-1901`` -> ``German``); ``None`` where PAGE names none
    (``grc``)."""
    tag = canonical(tag)
    return PAGE_LANGUAGE_NAMES.get(tag.partition("-")[0].lower()) if tag else None


def from_page_script(value: str | None) -> str | None:
    """The ISO 15924 code of a PAGE script value (``Latn - Latin`` -> ``Latn``); ``None`` for ``other`` or a value
    that is none."""
    code = (value or "").strip()[:4]
    return code if is_script(code) and (value or "").strip()[4:5] in ("", " ") else None


def page_script(code: str | None) -> str | None:
    """The PAGE script value of an ISO 15924 code (``Jpan`` -> ``Jpan - Japanese``); ``None`` where PAGE lists none."""
    return PAGE_SCRIPT_VALUES.get(code or "")
