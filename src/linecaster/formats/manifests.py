"""Items' manifests, read: an item's pages and their files, in reading order, from an IIIF Presentation manifest (2 or
3) or a METS document with MODS (plain, or the one record of an OAI-PMH ``GetRecord`` or ``ListRecords`` response).
``read_manifest`` returns a ``Manifest`` either way; ``read_collection`` the members of an IIIF Collection, one level;
``detect_format`` tells them apart by their content. JSON with ``json``, XML with lxml. Import-light: no datatrove,
saturate or engines.

A page's image is requested at full size: through its IIIF image service (an Image API request, ``image_url``) with
the image's own URL as the fallback, or a METS page's file in the first image file group that has one
(``METS_IMAGE_GROUPS``) with its file in the next as the fallback. A page's own OCR is the ALTO or hOCR file the
manifest links (IIIF ``seeAlso`` / ``rendering``; METS ``METS_OCR_GROUPS``)."""
from __future__ import annotations

import codecs
import json
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

__all__ = ["CollectionMember", "Manifest", "ManifestPage", "detect_format", "image_url", "label_text",
           "read_collection", "read_manifest"]

#: the namespaces read: METS, MODS, XLink, OAI-PMH, and the METS rights extension (``dv:rights``: the owner and the
#: license of a digitized item)
NAMESPACES = {
    "mets": "http://www.loc.gov/METS/",
    "mods": "http://www.loc.gov/mods/v3",
    "xlink": "http://www.w3.org/1999/xlink",
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dv": "http://dfg-viewer.de/",
}
_METS = f"{{{NAMESPACES['mets']}}}mets"
_DIV = f"{{{NAMESPACES['mets']}}}div"
_HREF = f"{{{NAMESPACES['xlink']}}}href"

#: METS file groups (``USE``) for a page's image, by priority: its file in the first that has one, the fallback its
#: file in the next (then any other group of ``image/*`` files, except thumbnails and OCR)
METS_IMAGE_GROUPS = ("MAX", "ORIGINAL", "MASTER", "DEFAULT")
#: METS file groups of a page's OCR: its file in the first that has one
METS_OCR_GROUPS = ("FULLTEXT", "ALTO", "OCR")
#: METS file groups never used for page images (thumbnails, small previews, local paths)
METS_EXCLUDED_IMAGE_GROUPS = frozenset({"THUMBS", "THUMB", "THUMBNAIL", "THUMBNAILS", "MIN", "LOCAL", "TEASER",
                                        "PREVIEW"})
_COLLECTION_TYPES = ("Collection", "sc:Collection")


@dataclass(frozen=True)
class ManifestPage:
    """One page of an item, with the image to fetch and its own OCR, if any.

    ``index``: the page's position (from 1) among the item's pages that have an image, in reading order. ``id``: the
    IIIF canvas id or the METS physical div's ``ID``; ``label`` the canvas label or the div's ``LABEL`` (else
    ``ORDERLABEL``). ``fallback_url`` is tried when ``url`` answers 404: for IIIF the image's own URL, for METS the
    page's file in the next image group. ``ocr_format``: ``alto`` or ``hocr``, None without ``ocr_url``."""

    index: int
    id: str | None
    label: str | None
    url: str
    fallback_url: str | None = None
    ocr_url: str | None = None
    ocr_format: str | None = None


@dataclass(frozen=True)
class Manifest:
    """An item as its manifest describes it.

    ``format``: ``iiif`` or ``mets``. ``id``: the IIIF manifest id, or the MODS ``recordIdentifier`` (else
    ``mets/@OBJID``). ``label``: the IIIF label, or the MODS title (``Title : Subtitle``). ``rights``: IIIF
    ``rights``/``license``, or the MODS ``accessCondition`` (else ``dv:license``). ``required_statement``: IIIF
    ``requiredStatement``/``attribution``, or the METS rights' owner (``dv:owner``). ``identifiers``: MODS identifiers
    by type (lower case) and ``recordIdentifier``; empty for IIIF. ``metadata``: JSON-serializable descriptive extras
    (IIIF: the manifest's metadata pairs; METS: creators, date, publisher, place, language, extent)."""

    format: str
    id: str | None
    label: str | None
    rights: str | None
    required_statement: str | None
    identifiers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    pages: list[ManifestPage] = field(default_factory=list)


@dataclass(frozen=True)
class CollectionMember:
    """One member of an IIIF Collection: its ``id`` (the URL to read it from), its ``label``, and its ``kind``,
    ``manifest`` or ``collection`` (a collection listed in the collection)."""

    id: str
    label: str | None
    kind: str


def detect_format(data: bytes | str | dict) -> str:
    """A manifest's format: ``iiif``, ``mets``, or ``iiif-collection`` for an IIIF Collection.

    ``iiif`` for JSON (or a dict) with an IIIF Presentation context, type ``Manifest`` or ``sequences``;
    ``iiif-collection`` for JSON of type ``Collection`` (3) or ``sc:Collection`` (2); ``mets`` for XML whose root is
    ``mets:mets``, or an OAI-PMH response with one ``mets:mets`` record. ``ValueError`` for anything else."""
    return _detect(_load(data))


def read_manifest(data: bytes | str | dict, format: str | None = None, *, iiif_format: str = "jpg",
                  iiif_quality: str = "default", image_groups: tuple[str, ...] = METS_IMAGE_GROUPS,
                  ocr_groups: tuple[str, ...] = METS_OCR_GROUPS) -> Manifest:
    """Read an IIIF or METS manifest.

    Args:
        data: the manifest, as fetched (bytes or text), or IIIF as a parsed dict.
        format: ``iiif`` or ``mets``; None tells them apart by content (``detect_format``).
        iiif_format, iiif_quality: the image format and quality asked of an IIIF image service (``image_url``).
        image_groups, ocr_groups: the METS file groups of the page images, by priority, and of the OCR.

    Raises:
        ValueError: the data cannot be read as a manifest of that format (an IIIF Collection included: read it with
            ``read_collection``).
    """
    loaded = _load(data)
    format = format or _detect(loaded)
    if format == "iiif-collection":
        raise ValueError("A IIIF Collection, not a manifest: read its members with read_collection()")
    if format == "iiif":
        if not isinstance(loaded, dict):
            raise ValueError("A IIIF manifest must be a JSON object")
        return _read_iiif(loaded, iiif_format, iiif_quality)
    if format == "mets":
        if not isinstance(loaded, etree._Element):
            raise ValueError("A METS document must be XML")
        return _read_mets(_mets_root(loaded), image_groups, ocr_groups)
    raise ValueError(f"Unknown manifest format: {format!r} (expected 'iiif' or 'mets')")


def read_collection(data: bytes | str | dict) -> list[CollectionMember]:
    """The members of an IIIF Collection (2 or 3), one level, in their order: the manifests and the collections it
    lists (3: ``items``; 2: ``members``, else ``collections`` then ``manifests``). A listed collection is a member of
    kind ``collection``, read by reading it in turn.

    Raises:
        ValueError: the data is not an IIIF Collection, or a member has no id.
        NotImplementedError: a paged collection (``first``/``next``), or one that embeds a nested collection's
            members; neither is read.
    """
    loaded = _load(data)
    if not isinstance(loaded, dict) or _detect(loaded) != "iiif-collection":
        raise ValueError("Not a IIIF Collection")
    if any(key in loaded for key in ("first", "next")):
        raise NotImplementedError("Paged IIIF Collections (first/next) are not read yet; read each page "
                                  "as a collection of its own")
    if "items" in loaded:
        members = [(m, None) for m in loaded["items"] or []]
    elif "members" in loaded:
        members = [(m, None) for m in loaded["members"] or []]
    else:
        members = [*((m, "collection") for m in loaded.get("collections") or []),
                   *((m, "manifest") for m in loaded.get("manifests") or [])]
    out = []
    for member, listed_as in members:
        if isinstance(member, str):      # 2 allows bare URIs in collections and manifests
            member = {"@id": member}
        if not isinstance(member, dict):
            continue
        member_id = member.get("id") or member.get("@id")
        if not member_id:
            raise ValueError(f"A IIIF Collection member without an id: {member!r}"[:200])
        kind = listed_as or ("collection" if (member.get("type") or member.get("@type")) in _COLLECTION_TYPES
                             else "manifest")
        if kind == "collection" and any(k in member for k in ("items", "members", "collections", "manifests")):
            raise NotImplementedError(f"The IIIF Collection embeds the members of a nested collection "
                                      f"({member_id}); nested collections are not read yet")
        out.append(CollectionMember(str(member_id), label_text(member.get("label")), kind))
    return out


# ------------------------------------------------------------------------------------------ loading and detection

def _parser() -> etree.XMLParser:
    """Comments and processing instructions dropped (they are no elements), internal entities resolved, nothing
    fetched."""
    return etree.XMLParser(remove_comments=True, remove_pis=True, resolve_entities="internal", no_network=True)


def _load(data: bytes | str | dict) -> dict | list | etree._Element:
    """JSON as parsed by ``json``, XML as an lxml element."""
    if isinstance(data, dict):
        return data
    if isinstance(data, bytes):
        start = data.removeprefix(codecs.BOM_UTF8).lstrip()[:1]
    elif isinstance(data, str):
        data = data.lstrip("﻿")
        start = data.lstrip()[:1].encode()
    else:
        # ValueError, not TypeError: read_manifest raises ValueError for anything unreadable
        raise ValueError(f"Cannot read a manifest from {type(data).__name__}")  # noqa: TRY004
    if start in (b"{", b"["):
        try:
            loaded: dict | list = json.loads(data)
            return loaded
        except ValueError as e:
            raise ValueError(f"Invalid JSON: {e}") from e
    if start == b"<":
        try:
            if isinstance(data, str):            # text: its own encoding declaration no longer applies
                parser = etree.XMLParser(remove_comments=True, remove_pis=True, resolve_entities="internal",
                                         no_network=True, encoding="utf-8")
                return etree.fromstring(data.lstrip().encode("utf-8"), parser)
            return etree.fromstring(data, _parser())
        except etree.XMLSyntaxError as e:
            raise ValueError(f"Invalid XML: {e}") from e
    raise ValueError("Neither JSON nor XML")


def _detect(loaded: dict | list | etree._Element) -> str:
    if isinstance(loaded, dict):
        if (loaded.get("type") or loaded.get("@type")) in _COLLECTION_TYPES:
            return "iiif-collection"
        context = loaded.get("@context") or loaded.get("context") or ""
        contexts = context if isinstance(context, list) else [context]
        if (loaded.get("type") == "Manifest" or loaded.get("@type") == "sc:Manifest" or "sequences" in loaded
                or any(isinstance(c, str) and "iiif.io/api/presentation" in c for c in contexts)):
            return "iiif"
        raise ValueError("JSON, but not a IIIF Presentation manifest")
    if isinstance(loaded, etree._Element):
        _mets_root(loaded)
        return "mets"
    raise ValueError("JSON, but not a IIIF Presentation manifest")


def _mets_root(root: etree._Element) -> etree._Element:
    """The ``mets:mets`` element: the root, or the one record of an OAI-PMH response."""
    if root.tag == _METS:
        return root
    records = root.findall(".//oai:record/oai:metadata/mets:mets", NAMESPACES)
    if len(records) == 1:
        return records[0]
    if len(records) > 1:
        raise ValueError(f"OAI-PMH response with {len(records)} METS records, expected one")
    raise ValueError(f"XML, but neither METS nor an OAI-PMH response with METS ({root.tag})")


# ------------------------------------------------------------------------------------------ IIIF

def label_text(value: Any) -> str | None:
    """The text of an IIIF label or value in any of its shapes, or None: 2: a string, a ``{"@value", "@language"}``
    object or a list of either; 3: a language map (``{"en": [...], "none": [...]}``). English first, then ``none``,
    then any language; several values joined with ``"; "``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts = [t for t in (label_text(v) for v in value) if t]
        return "; ".join(texts) or None
    if isinstance(value, dict):
        if "@value" in value:
            return label_text(value["@value"])
        for lang in ("en", "none", *value):
            if value.get(lang):
                return label_text(value[lang])
    return None


def _entries(value: Any) -> list[dict[str, Any]]:
    """An IIIF property that may be one entry or a list of them, as a list of dicts (a string becomes ``{"id"}``)."""
    if value is None:
        return []
    entries = value if isinstance(value, list) else [value]
    return [e if isinstance(e, dict) else {"id": e} for e in entries if isinstance(e, dict | str)]


@dataclass
class _Service:
    id: str
    type: Any = None
    profile: Any = None
    context: Any = None


@dataclass
class _Image:
    id: str
    service: _Service | None = None


@dataclass
class _Canvas:
    id: str
    label: str
    images: list[_Image]
    see_also: list[dict[str, Any]]
    rendering: list[dict[str, Any]]


def _service(data: dict[str, Any]) -> _Service:
    return _Service(id=data.get("@id") or data.get("id", ""), type=data.get("@type") or data.get("type"),
                    profile=data.get("profile"), context=data.get("@context") or data.get("context"))


def _image(data: dict[str, Any]) -> _Image:
    """An image resource (2) or annotation body (3); its first image service, if any."""
    services, service = data.get("service"), None
    if services:
        if isinstance(services, list) and services:
            service = _service(services[0])
        elif isinstance(services, dict):
            service = _service(services)
    return _Image(id=data.get("@id") or data.get("id", ""), service=service)


def _canvases_2(data: dict[str, Any]) -> list[_Canvas]:
    canvases = []
    for sequence in data.get("sequences", []):
        for canvas in sequence.get("canvases", []):
            images = [_image(r) for r in (i.get("resource", {}) for i in canvas.get("images", [])) if r]
            canvases.append(_Canvas(canvas.get("@id", ""), label_text(canvas.get("label")) or "", images,
                                    _entries(canvas.get("seeAlso")), _entries(canvas.get("rendering"))))
    return canvases


def _canvases_3(data: dict[str, Any]) -> list[_Canvas]:
    canvases = []
    for canvas in data.get("items", []):
        images = []
        for page in canvas.get("items", []):                     # canvas.items[].items[].body
            for annotation in page.get("items", []):
                body = annotation.get("body", {})
                if body:
                    images.append(_image(body))
        canvases.append(_Canvas(canvas.get("id", ""), label_text(canvas.get("label")) or "", images,
                                _entries(canvas.get("seeAlso")), _entries(canvas.get("rendering"))))
    return canvases


def image_api_version(service: _Service | None) -> int:
    """The IIIF Image API version (2 or 3) of an image service, from its type, context or profile; 2 when unknown."""
    if not service:
        return 2
    if service.type:
        if "ImageService3" in service.type:
            return 3
        if "ImageService2" in service.type:
            return 2
    if service.context:
        if "/image/3/" in service.context:
            return 3
        if "/image/2/" in service.context:
            return 2
    if service.profile:
        profile = service.profile if isinstance(service.profile, str) else str(service.profile)
        if "/image/3/" in profile:
            return 3
        if "/image/2/" in profile or "/image/1/" in profile:
            return 2
    return 2


def image_url(service_id: str, version: int = 2, iiif_format: str = "jpg", iiif_quality: str = "default") -> str:
    """The IIIF Image API request for a whole image at full size: ``{service}/full/{size}/0/{quality}.{format}``,
    where the size is ``max`` for Image API 3 and ``full`` for 2."""
    return f"{service_id.rstrip('/')}/full/{'max' if version == 3 else 'full'}/0/{iiif_quality}.{iiif_format}"


def _ocr_kind(entry: dict[str, Any]) -> str | None:
    """``alto`` or ``hocr`` when a ``seeAlso`` / ``rendering`` entry links OCR of that kind (by its format or
    profile), else None."""
    profile = entry.get("profile") or ""
    profile = " ".join(map(str, profile)) if isinstance(profile, list) else str(profile)
    hints = f"{entry.get('format') or ''} {profile}".lower()
    if "alto" in hints:
        return "alto"
    if "hocr" in hints:
        return "hocr"
    return None


def _iiif_ocr(canvas: _Canvas) -> tuple[str | None, str | None]:
    """The canvas's OCR link: ALTO before hOCR, ``seeAlso`` before ``rendering``."""
    found: dict[str, str] = {}
    for entry in canvas.see_also + canvas.rendering:
        kind, url = _ocr_kind(entry), entry.get("@id") or entry.get("id")
        if kind and isinstance(url, str) and url:
            found.setdefault(kind, url)
    for kind in ("alto", "hocr"):
        if kind in found:
            return found[kind], kind
    return None, None


def _read_iiif(data: dict[str, Any], iiif_format: str, iiif_quality: str) -> Manifest:
    if (data.get("type") or data.get("@type")) in _COLLECTION_TYPES:
        raise ValueError("A IIIF collection, not a manifest")
    try:
        if data.get("type") == "Manifest":                        # Presentation 3
            manifest_id, label, rights = data.get("id", ""), data.get("label"), data.get("rights")
            required = label_text((data.get("requiredStatement") or {}).get("value"))
            canvases = _canvases_3(data)
        elif "@context" in data or "sequences" in data:           # Presentation 2
            manifest_id, label = data.get("@id", ""), data.get("label", "")
            rights, required = label_text(data.get("license")), label_text(data.get("attribution"))
            canvases = _canvases_2(data)
        else:
            raise ValueError("Unable to determine IIIF manifest version")
        pairs = data.get("metadata", [])
        images = []                       # (canvas, its first image, url, fallback) per canvas with an image
        for canvas in canvases:
            if not canvas.images:
                continue
            image = canvas.images[0]
            if image.service:
                url = image_url(image.service.id, image_api_version(image.service), iiif_format, iiif_quality)
                fallback = image.id or None
            else:
                url, fallback = image.id, None
            if url:
                images.append((canvas, url, fallback))
    except (AttributeError, KeyError, TypeError) as e:
        raise ValueError(f"Invalid IIIF manifest: {e}") from e

    metadata: dict[str, Any] = {}
    for pair in pairs if isinstance(pairs, list) else []:
        if not isinstance(pair, dict):
            continue
        key, value = label_text(pair.get("label")), label_text(pair.get("value"))
        if key and value:
            metadata[key] = f"{metadata[key]}; {value}" if key in metadata else value
    pages = []
    for index, (canvas, url, fallback) in enumerate(images, 1):
        ocr_url, ocr_format = _iiif_ocr(canvas)
        pages.append(ManifestPage(index, canvas.id or None, canvas.label or None, url, fallback, ocr_url, ocr_format))
    return Manifest(format="iiif", id=manifest_id or None, label=label_text(label), rights=rights or None,
                    required_statement=required or None, identifiers={}, metadata=metadata, pages=pages)


# ------------------------------------------------------------------------------------------ METS

@dataclass
class _File:
    mimetype: str
    href: str
    use: str | None


@dataclass
class _Page:
    id: str
    label: str
    order_label: str | None
    file_ids: list[str]


def _text(elem: etree._Element | None) -> str | None:
    """The stripped text of an element, or None."""
    if elem is None or not elem.text or not elem.text.strip():
        return None
    return elem.text.strip()


def _join(values) -> str | None:
    """The distinct non-empty values joined with ``"; "``, or None."""
    return "; ".join(dict.fromkeys(v for v in values if v)) or None


def _find_mods(root: etree._Element) -> etree._Element | None:
    """The item's MODS record: the ``dmdSec`` referenced (``DMDID``) by the first div of the logical structMap that
    has one (the top div; for a volume of a multi-volume work, the volume's div below the anchor), else the first
    ``dmdSec`` with MODS, else any MODS element."""
    ns = NAMESPACES
    dmd_secs = {sec.get("ID"): sec for sec in root.findall("mets:dmdSec", ns)}
    for struct_map in root.findall("mets:structMap", ns):
        if (struct_map.get("TYPE") or "").upper() != "LOGICAL":
            continue
        for div in struct_map.iter(_DIV):
            for dmd_id in (div.get("DMDID") or "").split():
                sec = dmd_secs.get(dmd_id)
                mods = sec.find(".//mods:mods", ns) if sec is not None else None
                if mods is not None:
                    return mods
            if div.get("DMDID"):
                break
    for sec in dmd_secs.values():
        mods = sec.find(".//mods:mods", ns)
        if mods is not None:
            return mods
    return root.find(".//mods:mods", ns)


def _name_text(name: etree._Element) -> str | None:
    """A MODS name as text: ``displayForm``, else ``family, given``, else the untyped ``namePart``s."""
    ns = NAMESPACES
    display = _text(name.find("mods:displayForm", ns))
    if display:
        return display
    parts: dict[str, list[str]] = {}
    for part in name.findall("mods:namePart", ns):
        text = _text(part)
        if text:
            parts.setdefault(part.get("type") or "", []).append(text)
    family, given = " ".join(parts.get("family", [])), " ".join(parts.get("given", []))
    if family or given:
        return ", ".join(p for p in (family, given) if p)
    return " ".join(parts.get("", [])) or None


def _first_term(terms: list, kind: str):
    """The first term of ``type`` ``kind``, else the first term, else None."""
    return next((t for t in terms if t.get("type") == kind), terms[0] if terms else None)


def _is_digitization(origin: etree._Element) -> bool:
    """Whether an ``originInfo`` describes the digitization (``eventType``, or an edition ``[Electronic ed.]``)."""
    if (origin.get("eventType") or "").lower() == "digitization":
        return True
    return "electronic ed" in (_text(origin.find("mods:edition", NAMESPACES)) or "").lower()


def _date(dates: list) -> str | None:
    """The key date of several (``keyDate="yes"``), else a start-end range, else the first."""
    dates = [d for d in dates if _text(d)]
    if not dates:
        return None
    key = next((d for d in dates if d.get("keyDate") == "yes" and not d.get("point")), None)
    if key is not None:
        return _text(key)
    start = next((d for d in dates if d.get("point") == "start"), None)
    end = next((d for d in dates if d.get("point") == "end"), None)
    if start is not None and end is not None and _text(start) != _text(end):
        return f"{_text(start)}/{_text(end)}"
    return _text(start if start is not None else dates[0])


def _access_condition(conditions: list) -> str | None:
    """The rights of MODS ``accessCondition``s: a license URI (``xlink:href``), else the text of the ``use and
    reproduction`` one, else the first text."""
    use = [c for c in conditions if (c.get("type") or "").lower() == "use and reproduction"]
    for condition in use + conditions:
        uri = (condition.get(_HREF) or "").strip()
        if uri:
            return uri
    for condition in use + conditions:
        if _text(condition):
            return _text(condition)
    return None


def _mods(root: etree._Element) -> dict[str, Any]:
    """What the item's MODS record says (top-level elements only, not ``relatedItem``'s)."""
    out: dict[str, Any] = {"names": [], "languages": [], "identifiers": {}}
    mods = _find_mods(root)
    if mods is None:
        return out
    ns = NAMESPACES
    title_infos = mods.findall("mods:titleInfo", ns)          # the main one: no type (alternative, translated, ...)
    title_info = next((t for t in title_infos if not t.get("type")), title_infos[0] if title_infos else None)
    if title_info is not None:
        out["title"] = _text(title_info.find("mods:title", ns))
        out["subtitle"] = _text(title_info.find("mods:subTitle", ns))
        out["non_sort"] = _text(title_info.find("mods:nonSort", ns))
    for name in mods.findall("mods:name", ns):
        text = _name_text(name)
        if text:
            out["names"].append({"name": text, "role": _text(_first_term(name.findall("mods:role/mods:roleTerm", ns),
                                                                        "code")),
                                 "type": name.get("type")})
    origin = next((o for o in mods.findall("mods:originInfo", ns) if not _is_digitization(o)), None)
    if origin is not None:                                     # the first that is not the digitization's
        out["publisher"] = _join(_text(e) for e in origin.findall("mods:publisher", ns))
        out["date"] = _date(origin.findall("mods:dateIssued", ns)) or _date(origin.findall("mods:dateCreated", ns))
        out["place"] = _join(_text(_first_term(p.findall("mods:placeTerm", ns), "text"))
                             for p in origin.findall("mods:place", ns))
    for language in mods.findall("mods:language", ns):         # codes where given, else text
        code = _text(_first_term(language.findall("mods:languageTerm", ns), "code"))
        if code and code not in out["languages"]:
            out["languages"].append(code)
    out["extent"] = _join(_text(e) for e in mods.findall("mods:physicalDescription/mods:extent", ns))
    for identifier in mods.findall("mods:identifier", ns):
        kind, value = (identifier.get("type") or "").strip().lower(), _text(identifier)
        if kind and value:
            out["identifiers"].setdefault(kind, value)
    out["record_identifier"] = _text(mods.find("mods:recordInfo/mods:recordIdentifier", ns))
    out["license"] = _access_condition(mods.findall("mods:accessCondition", ns))
    return out


def _files(root: etree._Element) -> tuple[dict[str, _File], list[str]]:
    """The files of the file section by ``ID``, and the file groups' ``USE`` in document order."""
    ns = NAMESPACES
    files: dict[str, _File] = {}
    groups: list[str] = []
    file_sec = root.find(".//mets:fileSec", ns)
    if file_sec is None:
        return files, groups
    for group in file_sec.findall(".//mets:fileGrp", ns):
        use = group.get("USE")
        if use and use not in groups:
            groups.append(use)
        for f in group.findall(".//mets:file", ns):
            locations = f.findall("mets:FLocat", ns)        # a URL location over others (a local path)
            location = next((x for x in locations if (x.get("LOCTYPE") or "").upper() == "URL"),
                            locations[0] if locations else None)
            if location is not None and f.get("ID"):
                files[f.get("ID")] = _File(f.get("MIMETYPE", ""), location.get(_HREF, ""), use)
    return files, groups


def _pages(root: etree._Element) -> list[_Page]:
    """The page divs of the physical structMap, sorted by ``ORDER`` if every page has one, else in document order."""
    ns = NAMESPACES
    physical = next((m for m in root.findall(".//mets:structMap", ns) if (m.get("TYPE") or "").upper() == "PHYSICAL"),
                    None)
    if physical is None:
        return []
    pages, orders = [], []
    for div in physical.iter(_DIV):
        if (div.get("TYPE") or "").lower() != "page":
            continue
        try:
            orders.append(int(div.get("ORDER", "")))
        except ValueError:
            orders.append(None)
        file_ids: list[str] = []                  # fptr/@FILEID, and areas inside fptr (also within seq/par)
        for fptr in div.findall("mets:fptr", ns):
            ids = [fptr.get("FILEID"), *(area.get("FILEID") for area in fptr.findall(".//mets:area", ns))]
            file_ids += [i for i in ids if i and i not in file_ids]
        pages.append(_Page(div.get("ID", ""), div.get("LABEL", ""), div.get("ORDERLABEL") or None, file_ids))
    if None not in orders:
        pages = [p for _, p in sorted(zip(orders, pages, strict=True), key=lambda pair: pair[0])]
    return pages


def _page_file(page: _Page, files: dict[str, _File], groups: list[str]) -> _File | None:
    """The page's file in the first of ``groups`` (``USE``, upper case) that has one."""
    for group in groups:
        for file_id in page.file_ids:
            f = files.get(file_id)
            if f is not None and (f.use or "").upper() == group and f.href:
                return f
    return None


def _read_mets(root: etree._Element, image_groups: tuple[str, ...], ocr_groups: tuple[str, ...]) -> Manifest:
    ns = NAMESPACES
    try:
        record = root.find(".//oai:record/oai:metadata/mets:mets", ns)       # an OAI-PMH response inside
        root = record if record is not None else root
        files, file_groups = _files(root)
        mods, pages = _mods(root), _pages(root)
        owner = _text(root.find(".//dv:rights/dv:owner", ns))
        owner_license = _text(root.find(".//dv:rights/dv:license", ns))
        obj_id = root.get("OBJID") or None
    except Exception as e:
        raise ValueError(f"Failed to parse METS: {e}") from e

    label = mods.get("title")
    if label and mods.get("non_sort"):
        separator = "" if mods["non_sort"].endswith(("'", "’", "-")) else " "
        label = f"{mods['non_sort']}{separator}{label}"
    if label and mods.get("subtitle"):
        label = f"{label} : {mods['subtitle']}"
    identifiers = dict(mods["identifiers"])
    if mods.get("record_identifier"):
        identifiers["recordIdentifier"] = mods["record_identifier"]
    metadata: dict[str, Any] = {}
    if mods["names"]:
        metadata["creators"] = mods["names"]
    for key, value in (("date", mods.get("date")), ("publisher", mods.get("publisher")), ("place", mods.get("place")),
                       ("language", list(mods["languages"])), ("extent", mods.get("extent"))):
        if value:
            metadata[key] = value

    preferred = [g.upper() for g in image_groups]
    ocr = [g.upper() for g in ocr_groups]
    excluded = METS_EXCLUDED_IMAGE_GROUPS | set(ocr)
    others = [g.upper() for g in file_groups if g.upper() not in preferred and g.upper() not in excluded]
    # (USE, whether its files must be image/*): the groups asked for, then the document's others
    groups = [(g, False) for g in preferred] + [(g, True) for g in dict.fromkeys(others)]
    out: list[ManifestPage] = []
    for page in pages:
        images = []                                  # the page's image files, one per group that has one
        for group, must_be_image in groups:
            f = _page_file(page, files, [group])
            if f is None or not f.href:
                continue
            mimetype = f.mimetype.lower()
            if mimetype.startswith("image/") or (not must_be_image and not mimetype):
                images.append(f)
        if not images:
            continue
        text = _page_file(page, files, ocr)
        ocr_format = None
        if text is not None:
            mimetype = text.mimetype.lower()
            ocr_format = "hocr" if "hocr" in mimetype or "html" in mimetype else "alto"
        fallback = images[1].href if len(images) > 1 and images[1].href != images[0].href else None
        out.append(ManifestPage(len(out) + 1, page.id or None, page.label or page.order_label or None, images[0].href,
                                fallback, text.href if text is not None else None, ocr_format))
    return Manifest(format="mets", id=mods.get("record_identifier") or obj_id, label=label,
                    rights=mods.get("license") or owner_license, required_statement=owner, identifiers=identifiers,
                    metadata=metadata, pages=out)
