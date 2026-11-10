"""Items' manifests read by ``linecaster.formats.manifests``: IIIF Presentation 2 and 3 (pages, image requests,
fallbacks, OCR links, metadata), IIIF Collections (one level), METS with MODS (file groups, structMap order, areas,
OCR, metadata; plain and inside OAI-PMH), format detection. Fixtures inline and synthetic."""
import json

import pytest

from linecaster.formats.manifests import (CollectionMember, ManifestPage, _Service, detect_format, image_api_version,
                                          image_url, label_text, read_collection, read_manifest)

# A METS with MODS: MAX, DEFAULT, THUMBS and FULLTEXT groups, the page divs out of ORDER in the document, one page's
# fptr pointing into an area, one page without an image. The logical structMap's top div references DMDLOG_0001, not
# the first dmdSec. Rights in the METS rights extension (dv:rights).
METS_WITH_RIGHTS = """<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/" xmlns:mods="http://www.loc.gov/mods/v3"
           xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:dv="http://dfg-viewer.de/"
           OBJID="obj-1234">
  <mets:metsHdr CREATEDATE="2020-01-01T00:00:00Z"/>
  <mets:dmdSec ID="DMDLOG_0000">
    <mets:mdWrap MDTYPE="MODS"><mets:xmlData><mods:mods>
      <mods:titleInfo><mods:title>Wrong record (a chapter)</mods:title></mods:titleInfo>
    </mods:mods></mets:xmlData></mets:mdWrap>
  </mets:dmdSec>
  <mets:dmdSec ID="DMDLOG_0001">
    <mets:mdWrap MDTYPE="MODS"><mets:xmlData><mods:mods>
      <mods:titleInfo><mods:nonSort>Die</mods:nonSort><mods:title>Pflanzen der Heide</mods:title>
        <mods:subTitle>mit Abbildungen</mods:subTitle></mods:titleInfo>
      <mods:titleInfo type="alternative"><mods:title>Heideflora</mods:title></mods:titleInfo>
      <mods:name type="personal">
        <mods:namePart type="family">Müller</mods:namePart>
        <mods:namePart type="given">Karl</mods:namePart>
        <mods:role><mods:roleTerm authority="marcrelator" type="code">aut</mods:roleTerm></mods:role>
      </mods:name>
      <mods:name type="corporate"><mods:displayForm>Verlag Beispiel</mods:displayForm>
        <mods:role><mods:roleTerm type="text">Publisher</mods:roleTerm></mods:role></mods:name>
      <mods:originInfo eventType="publication">
        <mods:place><mods:placeTerm type="code">xx</mods:placeTerm>
          <mods:placeTerm type="text">Example Town</mods:placeTerm></mods:place>
        <mods:publisher>Beispiel</mods:publisher>
        <mods:dateIssued encoding="w3cdtf" keyDate="yes">1850</mods:dateIssued>
      </mods:originInfo>
      <mods:originInfo eventType="digitization">
        <mods:place><mods:placeTerm type="text">Example City</mods:placeTerm></mods:place>
        <mods:dateCaptured>2019</mods:dateCaptured><mods:publisher>Example Scanning</mods:publisher>
      </mods:originInfo>
      <mods:language><mods:languageTerm authority="iso639-2b" type="code">ger</mods:languageTerm></mods:language>
      <mods:language><mods:languageTerm authority="iso639-2b" type="code">lat</mods:languageTerm></mods:language>
      <mods:physicalDescription><mods:extent>XII, 340 S.</mods:extent></mods:physicalDescription>
      <mods:identifier type="urn">urn:example:1234</mods:identifier>
      <mods:identifier type="purl">https://purl.example.org/rec-1234</mods:identifier>
      <mods:identifier type="DOI">10.1234/example</mods:identifier>
      <mods:relatedItem type="series"><mods:titleInfo><mods:title>Series</mods:title></mods:titleInfo>
        <mods:identifier type="urn">urn:series</mods:identifier></mods:relatedItem>
      <mods:recordInfo><mods:recordIdentifier source="local">rec-1234</mods:recordIdentifier></mods:recordInfo>
      <mods:accessCondition type="use and reproduction"
        xlink:href="https://creativecommons.org/publicdomain/mark/1.0/">Public Domain Mark 1.0</mods:accessCondition>
    </mods:mods></mets:xmlData></mets:mdWrap>
  </mets:dmdSec>
  <mets:amdSec ID="AMD">
    <mets:rightsMD ID="RIGHTS"><mets:mdWrap MDTYPE="OTHER" OTHERMDTYPE="DVRIGHTS"><mets:xmlData>
      <dv:rights><dv:owner>Example Library</dv:owner><dv:license>pdm</dv:license></dv:rights>
    </mets:xmlData></mets:mdWrap></mets:rightsMD>
  </mets:amdSec>
  <mets:fileSec>
    <mets:fileGrp USE="DEFAULT">
      <mets:file ID="DEF_1" MIMETYPE="image/jpeg"><mets:FLocat LOCTYPE="URL" xlink:href="https://img.example.org/default/1.jpg"/></mets:file>
      <mets:file ID="DEF_2" MIMETYPE="image/jpeg"><mets:FLocat LOCTYPE="URL" xlink:href="https://img.example.org/default/2.jpg"/></mets:file>
      <mets:file ID="DEF_3" MIMETYPE="image/jpeg"><mets:FLocat LOCTYPE="URL" xlink:href="https://img.example.org/default/3.jpg"/></mets:file>
    </mets:fileGrp>
    <mets:fileGrp USE="THUMBS">
      <mets:file ID="THUMB_1" MIMETYPE="image/jpeg"><mets:FLocat LOCTYPE="URL" xlink:href="https://img.example.org/thumbs/1.jpg"/></mets:file>
      <mets:file ID="THUMB_4" MIMETYPE="image/jpeg"><mets:FLocat LOCTYPE="URL" xlink:href="https://img.example.org/thumbs/4.jpg"/></mets:file>
    </mets:fileGrp>
    <mets:fileGrp USE="MAX">
      <mets:file ID="MAX_1" MIMETYPE="image/jpeg"><mets:FLocat LOCTYPE="URL" xlink:href="https://img.example.org/max/1.jpg"/></mets:file>
      <mets:file ID="MAX_2" MIMETYPE="image/jpeg"><mets:FLocat LOCTYPE="URL" xlink:href="https://img.example.org/max/2.jpg"/></mets:file>
    </mets:fileGrp>
    <mets:fileGrp USE="FULLTEXT">
      <mets:file ID="ALTO_1" MIMETYPE="text/xml"><mets:FLocat LOCTYPE="URL" xlink:href="https://ocr.example.org/1.xml"/></mets:file>
      <mets:file ID="ALTO_3" MIMETYPE="application/alto+xml"><mets:FLocat LOCTYPE="URL" xlink:href="https://ocr.example.org/3.xml"/></mets:file>
    </mets:fileGrp>
  </mets:fileSec>
  <mets:structMap TYPE="LOGICAL">
    <mets:div ID="LOG_0" TYPE="monograph" DMDID="DMDLOG_0001" ADMID="AMD">
      <mets:div ID="LOG_1" TYPE="chapter" DMDID="DMDLOG_0000"/>
    </mets:div>
  </mets:structMap>
  <mets:structMap TYPE="PHYSICAL">
    <mets:div ID="PHYS_0000" TYPE="physSequence">
      <mets:div ID="PHYS_0002" TYPE="page" ORDER="2" ORDERLABEL="2">
        <mets:fptr FILEID="MAX_2"/><mets:fptr FILEID="DEF_2"/>
      </mets:div>
      <mets:div ID="PHYS_0001" TYPE="page" ORDER="1" ORDERLABEL="[1]" LABEL="Titelblatt">
        <mets:fptr FILEID="MAX_1"/><mets:fptr FILEID="DEF_1"/><mets:fptr FILEID="THUMB_1"/>
        <mets:fptr FILEID="ALTO_1"/>
      </mets:div>
      <mets:div ID="PHYS_0004" TYPE="page" ORDER="4" ORDERLABEL="4">
        <mets:fptr FILEID="THUMB_4"/>
      </mets:div>
      <mets:div ID="PHYS_0003" TYPE="Page" ORDER="3" ORDERLABEL="3">
        <mets:fptr><mets:seq><mets:area FILEID="DEF_3" BEGIN="1" END="1" BETYPE="IDREF"/></mets:seq></mets:fptr>
        <mets:fptr><mets:area FILEID="ALTO_3"/></mets:fptr>
      </mets:div>
    </mets:div>
  </mets:structMap>
</mets:mets>
"""

OAI_GETRECORD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
    "<responseDate>2026-01-01T00:00:00Z</responseDate>"
    '<request verb="GetRecord" metadataPrefix="mets">https://oai.example.org/</request>'
    "<GetRecord><record><header><identifier>oai:example:1234</identifier></header>"
    "<metadata>" + METS_WITH_RIGHTS.split("?>", 1)[1] + "</metadata></record></GetRecord></OAI-PMH>"
)

# No MAX group: DEFAULT is the image, without a fallback; no ORDER: document order. hOCR in an OCR group; rights
# only as text; no recordIdentifier: OBJID is the id.
METS_DEFAULT_ONLY = """<mets:mets xmlns:mets="http://www.loc.gov/METS/" xmlns:mods="http://www.loc.gov/mods/v3"
           xmlns:xlink="http://www.w3.org/1999/xlink" OBJID="obj-42">
  <mets:dmdSec ID="DMD1"><mets:mdWrap MDTYPE="MODS"><mets:xmlData><mods:mods>
    <mods:titleInfo><mods:title>Opera</mods:title></mods:titleInfo>
    <mods:name type="personal"><mods:namePart>Seneca, Lucius Annaeus</mods:namePart></mods:name>
    <mods:originInfo><mods:dateCreated>1500</mods:dateCreated></mods:originInfo>
    <mods:accessCondition type="use and reproduction">pdm</mods:accessCondition>
  </mods:mods></mets:xmlData></mets:mdWrap></mets:dmdSec>
  <mets:fileSec>
    <mets:fileGrp USE="DEFAULT">
      <mets:file ID="IMG_B" MIMETYPE="image/jpeg"><mets:FLocat LOCTYPE="URL" xlink:href="b.jpg"/></mets:file>
      <mets:file ID="IMG_A" MIMETYPE="image/jpeg"><mets:FLocat LOCTYPE="URL" xlink:href="a.jpg"/></mets:file>
    </mets:fileGrp>
    <mets:fileGrp USE="OCR">
      <mets:file ID="OCR_B" MIMETYPE="text/vnd.hocr+html"><mets:FLocat LOCTYPE="URL" xlink:href="b.hocr"/></mets:file>
    </mets:fileGrp>
  </mets:fileSec>
  <mets:structMap TYPE="PHYSICAL"><mets:div TYPE="physSequence">
    <mets:div ID="P_B" TYPE="page" LABEL="b"><mets:fptr FILEID="IMG_B"/><mets:fptr FILEID="OCR_B"/></mets:div>
    <mets:div ID="P_A" TYPE="page" LABEL="a"><mets:fptr FILEID="IMG_A"/></mets:div>
  </mets:div></mets:structMap>
</mets:mets>
"""

IIIF_V2 = {
    "@context": "http://iiif.io/api/presentation/2/context.json",
    "@id": "https://example.org/iiif/b1/manifest",
    "@type": "sc:Manifest",
    "label": [{"@value": "Flora", "@language": "en"}],
    "license": "https://creativecommons.org/publicdomain/mark/1.0/",
    "attribution": "Example Library",
    "metadata": [
        {"label": "Author", "value": "Müller, Karl"},
        {"label": [{"@value": "Date", "@language": "en"}], "value": "1850"},
    ],
    "sequences": [{"canvases": [
        {"@id": "https://example.org/iiif/b1/canvas/1", "label": "i",
         "seeAlso": {"@id": "https://example.org/alto/1.xml", "format": "application/xml",
                     "profile": "http://www.loc.gov/standards/alto/v3/alto.xsd"},
         "images": [{"resource": {
             "@id": "https://example.org/images/b1-1.jpg",
             "service": {"@context": "http://iiif.io/api/image/2/context.json",
                         "@id": "https://example.org/iiif/image/b1-1/",
                         "profile": "http://iiif.io/api/image/2/level2.json"}}}]},
        {"@id": "https://example.org/iiif/b1/canvas/2", "label": "blank", "images": []},
        {"@id": "https://example.org/iiif/b1/canvas/3", "label": "ii",
         "seeAlso": ["https://example.org/about.html"],
         "images": [{"resource": {"@id": "https://example.org/images/b1-3.jpg"}}]},
    ]}],
}

IIIF_V3 = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "id": "https://example.org/iiif/b2/manifest",
    "type": "Manifest",
    "label": {"de": ["Flora"]},
    "rights": "http://creativecommons.org/publicdomain/mark/1.0/",
    "requiredStatement": {"label": {"en": ["Attribution"]}, "value": {"en": ["Example Library"]}},
    "metadata": [{"label": {"en": ["Creator"]}, "value": {"none": ["Müller, Karl"]}}],
    "items": [{
        "id": "https://example.org/iiif/b2/canvas/1", "type": "Canvas", "label": {"none": ["1r"]},
        "seeAlso": [{"id": "https://example.org/b2/1.json", "type": "Dataset", "format": "application/json"}],
        "rendering": [
            {"id": "https://example.org/b2/1.pdf", "type": "Text", "format": "application/pdf"},
            {"id": "https://example.org/b2/1.hocr", "type": "Text", "format": "text/vnd.hocr+html"},
        ],
        "items": [{"type": "AnnotationPage", "items": [{"type": "Annotation", "body": {
            "id": "https://example.org/iiif/image/b2-1/full/max/0/default.jpg", "type": "Image",
            "service": [{"id": "https://example.org/iiif/image/b2-1", "type": "ImageService3",
                         "profile": "level1"}]}}]}],
    }],
}

COLLECTION_V3 = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "id": "https://library.test/iiif/collection/flora",
    "type": "Collection",
    "label": {"en": ["Flora"]},
    "items": [
        {"id": "https://library.test/iiif/b1/manifest", "type": "Manifest", "label": {"en": ["Volume 1"]}},
        {"id": "https://library.test/iiif/b2/manifest", "type": "Manifest", "label": {"none": ["Band 2"]}},
        {"id": "https://library.test/iiif/collection/fauna", "type": "Collection", "label": {"en": ["Fauna"]}},
    ],
}

COLLECTION_V2 = {
    "@context": "http://iiif.io/api/presentation/2/context.json",
    "@id": "https://library.test/iiif/collection/top",
    "@type": "sc:Collection",
    "label": "Top",
    "collections": [{"@id": "https://library.test/iiif/collection/sub", "@type": "sc:Collection", "label": "Sub"}],
    "manifests": [{"@id": "https://library.test/iiif/b3/manifest", "@type": "sc:Manifest", "label": "Volume 3"},
                  "https://library.test/iiif/b4/manifest"],
}

#: every manifest fixture here, for tests that run over all of them
FIXTURES = {"mets_with_rights": METS_WITH_RIGHTS, "oai_getrecord": OAI_GETRECORD,
            "mets_default_only": METS_DEFAULT_ONLY, "iiif_v2": IIIF_V2, "iiif_v3": IIIF_V3}


# ------------------------------------------------------------------------------------------ detect_format

@pytest.mark.parametrize("data, expected", [
    (IIIF_V2, "iiif"),
    (IIIF_V3, "iiif"),
    (json.dumps(IIIF_V3), "iiif"),
    (json.dumps(IIIF_V2).encode(), "iiif"),
    ({"@context": ["http://iiif.io/api/presentation/3/context.json"], "id": "x"}, "iiif"),
    (METS_WITH_RIGHTS, "mets"),
    (METS_WITH_RIGHTS.encode(), "mets"),
    ("﻿  " + METS_WITH_RIGHTS, "mets"),
    (OAI_GETRECORD, "mets"),
    (METS_DEFAULT_ONLY, "mets"),
    (COLLECTION_V3, "iiif-collection"),
    (COLLECTION_V2, "iiif-collection"),
])
def test_detect_format(data, expected):
    assert detect_format(data) == expected


@pytest.mark.parametrize("junk", [
    b"", "hello", "{not json", "[1, 2]", {"foo": "bar"}, "<html><body/></html>", "<a><b>",
    '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><error code="idDoesNotExist"/></OAI-PMH>',
    42,
])
def test_detect_format_rejects_junk(junk):
    with pytest.raises(ValueError):
        detect_format(junk)


def test_read_manifest_rejects_mismatches():
    with pytest.raises(ValueError):
        read_manifest(METS_WITH_RIGHTS, format="iiif")
    with pytest.raises(ValueError):
        read_manifest(IIIF_V3, format="mets")
    with pytest.raises(ValueError):
        read_manifest(IIIF_V3, format="pdf")
    with pytest.raises(ValueError):
        read_manifest({"@context": "http://iiif.io/api/presentation/3/context.json", "type": "Collection",
                       "items": []})
    two_records = OAI_GETRECORD.replace("</record>", "</record>" + OAI_GETRECORD.split(
        "<GetRecord>")[1].split("</GetRecord>")[0], 1)
    with pytest.raises(ValueError, match="2 METS records"):
        read_manifest(two_records)
    with pytest.raises(ValueError, match="Invalid IIIF manifest"):
        read_manifest({**IIIF_V2, "sequences": [None]})


# ------------------------------------------------------------------------------------------ METS

def test_mets_pages():
    item = read_manifest(METS_WITH_RIGHTS)
    assert item.format == "mets"
    assert item.pages == [
        ManifestPage(1, "PHYS_0001", "Titelblatt", "https://img.example.org/max/1.jpg",
                     "https://img.example.org/default/1.jpg", "https://ocr.example.org/1.xml", "alto"),
        ManifestPage(2, "PHYS_0002", "2", "https://img.example.org/max/2.jpg",
                     "https://img.example.org/default/2.jpg", None, None),
        # fptr/seq/area, TYPE="Page"; no MAX file for this page, so DEFAULT without fallback
        ManifestPage(3, "PHYS_0003", "3", "https://img.example.org/default/3.jpg", None,
                     "https://ocr.example.org/3.xml", "alto"),
        # PHYS_0004 has only a thumbnail: no page
    ]


def test_mets_metadata():
    item = read_manifest(METS_WITH_RIGHTS)
    assert item.id == "rec-1234"
    assert item.label == "Die Pflanzen der Heide : mit Abbildungen"
    assert item.rights == "https://creativecommons.org/publicdomain/mark/1.0/"
    assert item.required_statement == "Example Library"
    assert item.identifiers == {"urn": "urn:example:1234", "purl": "https://purl.example.org/rec-1234",
                                "doi": "10.1234/example", "recordIdentifier": "rec-1234"}
    assert item.metadata == {
        "creators": [
            {"name": "Müller, Karl", "role": "aut", "type": "personal"},
            {"name": "Verlag Beispiel", "role": "Publisher", "type": "corporate"},
        ],
        "date": "1850",
        "publisher": "Beispiel",  # not the digitization's
        "place": "Example Town",
        "language": ["ger", "lat"],
        "extent": "XII, 340 S.",
    }
    json.dumps(item.metadata)


def test_oai_pmh_reads_like_the_plain_mets():
    assert read_manifest(OAI_GETRECORD) == read_manifest(METS_WITH_RIGHTS)
    assert read_manifest(OAI_GETRECORD.encode(), format="mets").id == "rec-1234"
    list_records = OAI_GETRECORD.replace("GetRecord>", "ListRecords>")
    assert read_manifest(list_records) == read_manifest(METS_WITH_RIGHTS)


def test_mets_without_max_uses_default_in_document_order():
    item = read_manifest(METS_DEFAULT_ONLY)
    assert [(p.index, p.id, p.label, p.url, p.fallback_url, p.ocr_url, p.ocr_format) for p in item.pages] == [
        (1, "P_B", "b", "b.jpg", None, "b.hocr", "hocr"),  # relative hrefs kept as given
        (2, "P_A", "a", "a.jpg", None, None, None),
    ]
    assert (item.id, item.label, item.rights, item.required_statement) == ("obj-42", "Opera", "pdm", None)
    assert item.identifiers == {}
    assert item.metadata == {"creators": [{"name": "Seneca, Lucius Annaeus", "role": None, "type": "personal"}],
                             "date": "1500"}


def test_mets_image_groups_given():
    item = read_manifest(METS_WITH_RIGHTS, image_groups=("DEFAULT", "MAX"))
    assert [(p.url, p.fallback_url) for p in item.pages] == [
        ("https://img.example.org/default/1.jpg", "https://img.example.org/max/1.jpg"),
        ("https://img.example.org/default/2.jpg", "https://img.example.org/max/2.jpg"),
        ("https://img.example.org/default/3.jpg", None),
    ]


def test_mets_other_image_groups_but_never_thumbnails():
    # neither MAX nor DEFAULT: PRESENTATION (image/*) is used; THUMBS never
    mets = (METS_DEFAULT_ONLY.replace('USE="DEFAULT"', 'USE="PRESENTATION"')
            .replace('<mets:fileGrp USE="OCR">', '<mets:fileGrp USE="THUMBS"><mets:file ID="T_A" '
                     'MIMETYPE="image/jpeg"><mets:FLocat xlink:href="t.jpg"/></mets:file>'
                     '</mets:fileGrp><mets:fileGrp USE="OCR">')
            .replace('<mets:fptr FILEID="IMG_A"/>', '<mets:fptr FILEID="T_A"/>'))
    assert [(p.id, p.url) for p in read_manifest(mets).pages] == [("P_B", "b.jpg")]


def test_mets_as_text_with_another_encoding_declared_and_comments():
    """Text is text: an encoding declaration does not apply to it; comments and processing instructions are no
    elements."""
    text = METS_DEFAULT_ONLY.replace('<mets:fileSec>', '<!-- files --><?note x?><mets:fileSec>')
    text = '<?xml version="1.0" encoding="ISO-8859-1"?>\n' + text.replace("Opera", "Opéra")
    item = read_manifest(text)
    assert item.label == "Opéra" and [p.id for p in item.pages] == ["P_B", "P_A"]
    assert read_manifest(text.encode("iso-8859-1")).label == "Opéra"


# ------------------------------------------------------------------------------------------ IIIF

def test_iiif_v2():
    item = read_manifest(json.dumps(IIIF_V2).encode())
    assert (item.format, item.id, item.label, item.rights, item.required_statement) == (
        "iiif", "https://example.org/iiif/b1/manifest", "Flora",
        "https://creativecommons.org/publicdomain/mark/1.0/", "Example Library")
    assert item.identifiers == {}
    assert item.metadata == {"Author": "Müller, Karl", "Date": "1850"}
    assert item.pages == [
        ManifestPage(1, "https://example.org/iiif/b1/canvas/1", "i",
                     "https://example.org/iiif/image/b1-1/full/full/0/default.jpg",
                     "https://example.org/images/b1-1.jpg", "https://example.org/alto/1.xml", "alto"),
        ManifestPage(2, "https://example.org/iiif/b1/canvas/3", "ii",
                     "https://example.org/images/b1-3.jpg", None, None, None),     # no service: its own URL
    ]


def test_iiif_v3_hocr_rendering():
    item = read_manifest(IIIF_V3)
    assert (item.format, item.id, item.label, item.rights, item.required_statement) == (
        "iiif", "https://example.org/iiif/b2/manifest", "Flora",
        "http://creativecommons.org/publicdomain/mark/1.0/", "Example Library")
    assert item.metadata == {"Creator": "Müller, Karl"}
    assert item.pages == [ManifestPage(
        1, "https://example.org/iiif/b2/canvas/1", "1r",
        "https://example.org/iiif/image/b2-1/full/max/0/default.jpg",
        "https://example.org/iiif/image/b2-1/full/max/0/default.jpg",
        "https://example.org/b2/1.hocr", "hocr")]


def test_iiif_v3_alto_see_also_preferred_over_hocr():
    data = json.loads(json.dumps(IIIF_V3))
    data["items"][0]["seeAlso"].append(
        {"id": "https://example.org/b2/1.alto.xml", "type": "Dataset", "format": "application/alto+xml"})
    page = read_manifest(data).pages[0]
    assert (page.ocr_url, page.ocr_format) == ("https://example.org/b2/1.alto.xml", "alto")


def test_iiif_format_and_quality():
    [page] = read_manifest(IIIF_V3, iiif_format="png", iiif_quality="gray").pages
    assert page.url == "https://example.org/iiif/image/b2-1/full/max/0/gray.png"
    assert read_manifest(IIIF_V2, iiif_format="png").pages[0].url == (
        "https://example.org/iiif/image/b1-1/full/full/0/default.png")


@pytest.mark.parametrize("service, version", [
    (_Service("s", type="ImageService3"), 3),
    (_Service("s", type="ImageService2"), 2),
    (_Service("s", context="http://iiif.io/api/image/3/context.json"), 3),
    (_Service("s", profile="http://iiif.io/api/image/1/level1.json"), 2),
    (_Service("s", profile=["http://iiif.io/api/image/3/level1.json"]), 3),
    (_Service("s"), 2),
    (None, 2),
])
def test_image_api_version(service, version):
    assert image_api_version(service) == version


def test_image_url():
    assert image_url("https://example.org/iiif/x/", 2) == "https://example.org/iiif/x/full/full/0/default.jpg"
    assert image_url("https://example.org/iiif/x", 3, "webp", "color") == (
        "https://example.org/iiif/x/full/max/0/color.webp")


@pytest.mark.parametrize("value, text", [
    ("Flora", "Flora"),
    ({"@value": "Flora", "@language": "la"}, "Flora"),
    ([{"@value": "Flora"}, "Band 1"], "Flora; Band 1"),
    ({"fr": ["Flore"], "en": ["Flora"]}, "Flora"),
    ({"none": ["1r"]}, "1r"),
    ({}, None),
    (None, None),
])
def test_label_text(value, text):
    assert label_text(value) == text


# ------------------------------------------------------------------------------------------ read_collection

def test_read_collection_v3_and_v2():
    assert read_collection(json.dumps(COLLECTION_V3).encode()) == [
        CollectionMember("https://library.test/iiif/b1/manifest", "Volume 1", "manifest"),
        CollectionMember("https://library.test/iiif/b2/manifest", "Band 2", "manifest"),
        CollectionMember("https://library.test/iiif/collection/fauna", "Fauna", "collection"),
    ]
    assert [(e.kind, e.id, e.label) for e in read_collection(COLLECTION_V2)] == [
        ("collection", "https://library.test/iiif/collection/sub", "Sub"),
        ("manifest", "https://library.test/iiif/b3/manifest", "Volume 3"),
        ("manifest", "https://library.test/iiif/b4/manifest", None),
    ]
    with pytest.raises(ValueError, match="read_collection"):
        read_manifest(COLLECTION_V3)
    with pytest.raises(ValueError, match="Not a IIIF Collection"):
        read_collection(IIIF_V3)


def test_paged_and_embedded_nested_collections_are_not_read():
    with pytest.raises(NotImplementedError, match="Paged"):
        read_collection({**COLLECTION_V2, "first": "https://library.test/iiif/collection/top?page=1"})
    nested = {**COLLECTION_V3, "items": [{**COLLECTION_V3["items"][2], "items": COLLECTION_V3["items"][:1]}]}
    with pytest.raises(NotImplementedError, match="nested"):
        read_collection(nested)
