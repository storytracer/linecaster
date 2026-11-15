"""Pages in twelve writing systems and all four writing directions, built in code, for tests of everything that
depends on a script or a direction: tokenizers, lanes, renderings, importers, reading order.

``SCRIPT_SAMPLES`` holds the samples by id (``latin``, ``fraktur``, ``greek``, ``cyrillic``, ``arabic``,
``hebrew``, ``devanagari``, ``thai``, ``chinese``, ``japanese``, ``korean``, ``mongolian``): each with its language
(a BCP 47 tag), script (an ISO 15924 code), direction (``linecaster.data.writing.DIRECTIONS``) and its text, two
regions of lines in reading order. ``script_page(id)`` lays a sample out as a transcription on a 1000 x 1400 page in
its direction: the regions side by side as columns for a horizontal direction (the first on the side the lines
start, left or right), one above the other for a vertical one, their lines stacked in the direction (rows top to
bottom; columns from the right for ``vertical-rl``, from the left for ``vertical-lr``). The page records the
sample's language, script and direction (classifications by a ``source`` annotator), a reading order, and every
line's text.

The texts are short public-domain or common phrases; a sample's words are what ``scoring.tokens`` counts.

``script_image(id)`` draws a sample's page as an image, each line in its box and direction, with an installed font
that covers its characters (found through fontconfig's ``fc-list``, or given), shaped by Pillow's libraqm; a
``LookupError`` where no font or no shaping is at hand (tests skip then). Vertical text is set top to bottom
(Mongolian's rotated letters turned with their line).
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from ..data import Annotator, Source, Transcription

#: the page every sample is laid out on
PAGE_WIDTH, PAGE_HEIGHT = 1000, 1400


@dataclass(frozen=True)
class ScriptSample:
    """A writing system's sample.

    Args:
        id: its name (``SCRIPT_SAMPLES``' key).
        language: its language, a BCP 47 tag.
        script: its script, an ISO 15924 code.
        direction: its writing direction (``linecaster.data.writing.DIRECTIONS``).
        regions: each region's lines (their texts), in reading order.
    """

    id: str
    language: str
    script: str
    direction: str
    regions: tuple[tuple[str, ...], ...]

    @property
    def lines(self) -> list[str]:
        return [s for region in self.regions for s in region]


SCRIPT_SAMPLES: dict[str, ScriptSample] = {s.id: s for s in (
    ScriptSample("latin", "en", "Latn", "horizontal-lr",
                 (("The ship sailed at dawn,", "and the crew sang."), ("Night fell over the harbor.",))),
    ScriptSample("fraktur", "de", "Latf", "horizontal-lr",
                 (("Die ſchöne Stadt liegt", "am Ufer des Fluſſes."), ("Es war einmal ein König.",))),
    ScriptSample("greek", "grc", "Grek", "horizontal-lr",
                 (("Ἐν ἀρχῇ ἦν ὁ λόγος,", "καὶ ὁ λόγος ἦν πρὸς τὸν θεόν."), ("οὗτος ἦν ἐν ἀρχῇ.",))),
    ScriptSample("cyrillic", "ru", "Cyrl", "horizontal-lr",
                 (("Въ началѣ было Слово,", "и Слово было у Бога."), ("Міръ и вѣра.",))),
    ScriptSample("arabic", "ar", "Arab", "horizontal-rl",
                 (("بسم الله الرحمن الرحيم", "الحمد لله رب العالمين"), ("كَتَبَ الوَلَدُ الدَّرْسَ",))),
    ScriptSample("hebrew", "he", "Hebr", "horizontal-rl",
                 (("בְּרֵאשִׁית בָּרָא אֱלֹהִים", "אֵת הַשָּׁמַיִם וְאֵת הָאָרֶץ"), ("שָׁלוֹם עוֹלָם",))),
    ScriptSample("devanagari", "hi", "Deva", "horizontal-lr",
                 (("नमस्ते दुनिया", "यह एक परीक्षा है।"), ("हिन्दी भाषा",))),
    ScriptSample("thai", "th", "Thai", "horizontal-lr",
                 (("สวัสดีครับ วันนี้", "อากาศดีมาก"), ("ภาษาไทย",))),
    ScriptSample("chinese", "zh-Hant", "Hani", "vertical-rl",
                 (("天地玄黃", "宇宙洪荒"), ("日月盈昃", "辰宿列張"))),
    ScriptSample("japanese", "ja", "Jpan", "vertical-rl",
                 (("東京は晴れです", "今日はいい天気ですね"), ("カタカナとひらがな",))),
    ScriptSample("korean", "ko", "Kore", "horizontal-lr",
                 (("한국어 텍스트입니다", "오늘은 날씨가 좋습니다"), ("漢字와 한글",))),
    ScriptSample("mongolian", "mn-Mong", "Mong", "vertical-lr",
                 (("ᠮᠣᠩᠭᠣᠯ ᠪᠢᠴᠢᠭ", "ᠰᠠᠢᠨ ᠪᠠᠢᠨ᠎ᠠ ᠤᠤ"), ("ᠮᠣᠩᠭᠣᠯ ᠬᠡᠯᠡ",))),
)}

_MARGIN, _GAP, _THICK, _STEP = 50, 50, 40, 60       # page margin, gap between regions, a line's height, its pitch


def _region_boxes(direction: str, n: int) -> list[tuple[float, float, float, float]]:
    """The regions' boxes (x0, y0, x1, y1) in reading order."""
    if direction.startswith("horizontal"):
        width = (PAGE_WIDTH - 2 * _MARGIN - (n - 1) * _GAP) / n
        boxes = [(_MARGIN + k * (width + _GAP), _MARGIN, _MARGIN + k * (width + _GAP) + width, PAGE_HEIGHT - _MARGIN)
                 for k in range(n)]
        return boxes[::-1] if direction == "horizontal-rl" else boxes
    height = (PAGE_HEIGHT - 2 * _MARGIN - (n - 1) * _GAP) / n
    return [(_MARGIN, _MARGIN + k * (height + _GAP), PAGE_WIDTH - _MARGIN, _MARGIN + k * (height + _GAP) + height)
            for k in range(n)]


def _line_box(direction: str, region: tuple[float, float, float, float], i: int) -> list[float]:
    """The ``i``-th line's box in ``region`` as [x, y, width, height]."""
    x0, y0, x1, y1 = region
    if direction.startswith("horizontal"):
        return [x0, y0 + i * _STEP, x1 - x0, _THICK]
    x = x1 - _THICK - i * _STEP if direction == "vertical-rl" else x0 + i * _STEP
    return [x, y0, _THICK, y1 - y0]


def script_page(sample: str | ScriptSample) -> Transcription:
    """The sample laid out on a page in its direction, with its language, script, direction, reading order and
    texts recorded (the module's docstring).

    Args:
        sample: a sample or its id (``SCRIPT_SAMPLES``).
    """
    s = SCRIPT_SAMPLES[sample] if isinstance(sample, str) else sample
    t = Transcription(source=Source(image_width=PAGE_WIDTH, image_height=PAGE_HEIGHT, uri=f"{s.id}.png"))
    a = t.add_annotator(Annotator(step="source", name="script samples"))
    for scheme, value in (("language", s.language), ("script", s.script), ("direction", s.direction)):
        t.classify(a, "", scheme, value)
    region_ids, line_ids = [], []
    for k, (texts, (x0, y0, x1, y1)) in enumerate(zip(s.regions, _region_boxes(s.direction, len(s.regions)))):
        rid = f"r{k}"
        t.add_region(a, rid, [x0, y0, x1 - x0, y1 - y0], role="paragraph")
        region_ids.append(rid)
        for i, text in enumerate(texts):
            lid = f"{rid}l{i}"
            t.add_line(a, lid, _line_box(s.direction, (x0, y0, x1, y1), i), region=rid, text=text)
            line_ids.append(lid)
    t.add_order(a, region_ids, line_ids)
    return t


def _font(s: ScriptSample) -> tuple[str, int]:
    """An installed font (its file and index in a collection) that has every character of the sample: of the
    sample's language first; an outline font, a regular style, DejaVu, then Noto before others."""
    if shutil.which("fc-list") is None:
        raise LookupError("fontconfig's fc-list is not installed")
    chars = " ".join(f"{ord(c):x}" for c in sorted(set("".join(s.lines))) if not c.isspace())
    for pattern in (f":lang={s.language.split('-')[0]}:charset={chars}", f":charset={chars}"):
        listed = subprocess.run(["fc-list", pattern, "-f", "%{file}|%{index}|%{style}\n"], capture_output=True,
                                text=True, check=False).stdout.split("\n")
        fonts = sorted((not file.endswith((".ttf", ".otf", ".ttc")), "Regular" not in style and "Book" not in style,
                        next((k for k, family in enumerate(("DejaVu", "Noto")) if family in file), 2), file,
                        int(index or 0))
                       for file, index, style in (line.split("|", 2) for line in listed if line.count("|") == 2))
        if fonts:
            return fonts[0][3], fonts[0][4]
    raise LookupError(f"no installed font has every character of the {s.id} sample")


def script_image(sample: str | ScriptSample, font: str | None = None, size: int = 28):
    """The sample's page as an RGB image (``PAGE_WIDTH`` x ``PAGE_HEIGHT``, ``PIL.Image``), its lines drawn in their
    boxes (``script_page``) in their direction.

    Args:
        sample: a sample or its id (``SCRIPT_SAMPLES``).
        font: a font file; ``None``: an installed one that has the sample's characters.
        size: the font size in pixels.
    """
    from PIL import Image, ImageDraw, ImageFont, features

    s = SCRIPT_SAMPLES[sample] if isinstance(sample, str) else sample
    if not features.check("raqm"):
        raise LookupError("Pillow has no libraqm: complex scripts would not be shaped")
    path, index = (font, 0) if font else _font(s)
    face = ImageFont.truetype(path, size, index=index, layout_engine=ImageFont.Layout.RAQM)
    image = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    t = script_page(s)
    language = s.language.split("-")[0]
    for ln in t.ordered_lines():
        x, y, w, h = ln.box
        text = t.text_of(ln) or ""
        if s.direction.startswith("horizontal"):
            rtl = s.direction == "horizontal-rl"
            draw.text((x + w if rtl else x, y + h / 2), text, fill="black", font=face, anchor="rm" if rtl else "lm",
                      direction="rtl" if rtl else "ltr", language=language)
        elif s.script == "Mong":           # Mongolian: the line set horizontally, turned clockwise
            strip = Image.new("RGB", (round(h), round(w)), "white")
            ImageDraw.Draw(strip).text((0, w / 2), text, fill="black", font=face, anchor="lm", language=language)
            image.paste(strip.rotate(-90, expand=True), (round(x), round(y)))
        else:
            draw.text((x + w / 2, y), text, fill="black", font=face, anchor="mt", direction="ttb",
                      language=language)
    return image


__all__ = ["PAGE_HEIGHT", "PAGE_WIDTH", "SCRIPT_SAMPLES", "ScriptSample", "script_image", "script_page"]
