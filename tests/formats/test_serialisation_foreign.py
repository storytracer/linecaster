"""Reading ALTO, PAGE and hOCR as libraries and other tools write them."""
from __future__ import annotations

import pytest

from linecaster.formats import from_alto, from_hocr, from_page

ALTO_V2_MM10 = b"""<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v2#" xmlns:xlink="http://www.w3.org/1999/xlink">
  <Description>
    <MeasurementUnit>mm10</MeasurementUnit>
    <sourceImageInformation><fileName>0001.jp2</fileName></sourceImageInformation>
  </Description>
  <Layout>
    <Page ID="P1" PHYSICAL_IMG_NR="1" WIDTH="2100" HEIGHT="2970">
      <TopMargin HPOS="0" VPOS="0" WIDTH="2100" HEIGHT="200">
        <TextBlock ID="TB0" HPOS="100" VPOS="100" WIDTH="400" HEIGHT="50">
          <TextLine HPOS="100" VPOS="100" WIDTH="400" HEIGHT="50" BASELINE="140">
            <String CONTENT="CHAPTER" HPOS="100" VPOS="100" WIDTH="250" HEIGHT="50" WC="0.91"/>
            <SP WIDTH="20"/>
            <String CONTENT="I." HPOS="370" VPOS="100" WIDTH="60" HEIGHT="50" WC="0.80"/>
          </TextLine>
        </TextBlock>
      </TopMargin>
      <PrintSpace HPOS="100" VPOS="200" WIDTH="1900" HEIGHT="2600">
        <ComposedBlock ID="CB1" HPOS="100" VPOS="200" WIDTH="1900" HEIGHT="800">
          <TextBlock ID="TB1" HPOS="100" VPOS="200" WIDTH="1900" HEIGHT="120">
            <TextLine ID="TL1" HPOS="100" VPOS="200" WIDTH="1900" HEIGHT="50" BASELINE="245">
              <String ID="S1" CONTENT="It" HPOS="100" VPOS="200" WIDTH="60" HEIGHT="50" WC="0.99"/>
              <SP/>
              <String ID="S2" CONTENT="was" HPOS="180" VPOS="200" WIDTH="100" HEIGHT="50" WC="0.98"/>
              <SP/>
              <String ID="S3" CONTENT="consider" SUBS_TYPE="HypPart1" SUBS_CONTENT="considerable"
                      HPOS="300" VPOS="200" WIDTH="250" HEIGHT="50" WC="0.7"/>
              <HYP CONTENT="-"/>
            </TextLine>
            <TextLine ID="TL2" HPOS="100" VPOS="260" WIDTH="900" HEIGHT="50">
              <String ID="S4" CONTENT="able" SUBS_TYPE="HypPart2" SUBS_CONTENT="considerable"
                      HPOS="100" VPOS="260" WIDTH="150" HEIGHT="50"/>
            </TextLine>
          </TextBlock>
          <Illustration ID="IL1" HPOS="100" VPOS="400" WIDTH="1900" HEIGHT="600"/>
        </ComposedBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
"""

ALTO_V3_NO_NS = b"""<?xml version="1.0"?>
<alto>
  <Description><MeasurementUnit>pixel</MeasurementUnit></Description>
  <Tags>
    <StructureTag ID="ST1" LABEL="heading"/>
    <StructureTag ID="ST2" LABEL="paragraph"/>
  </Tags>
  <Layout>
    <Page ID="p" PHYSICAL_IMG_NR="1" WIDTH="1000" HEIGHT="1500">
      <PrintSpace>
        <TextBlock ID="b1" HPOS="10" VPOS="10" WIDTH="500" HEIGHT="40" TAGREFS="ST1">
          <TextLine ID="b1l1" HPOS="10" VPOS="10" WIDTH="500" HEIGHT="40">
            <String ID="b1l1s1" CONTENT="Introduction" HPOS="10" VPOS="10" WIDTH="300" HEIGHT="40"/>
          </TextLine>
        </TextBlock>
        <TextBlock ID="b2" HPOS="10" VPOS="60" WIDTH="900" HEIGHT="40" TAGREFS="ST2">
          <TextLine ID="b2l1" HPOS="10" VPOS="60" WIDTH="900" HEIGHT="40">
            <String ID="b2l1s1" CONTENT="Text" HPOS="10" VPOS="60" WIDTH="100" HEIGHT="40" WC="0.5"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
"""

ALTO_V4_ESCRIPTORIUM = b"""<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v4#">
  <Description><MeasurementUnit>pixel</MeasurementUnit></Description>
  <Tags>
    <OtherTag ID="BT1" LABEL="MainZone" DESCRIPTION="block type MainZone"/>
    <OtherTag ID="LT1" LABEL="default" DESCRIPTION="line type default"/>
  </Tags>
  <ReadingOrder>
    <OrderedGroup ID="ro"><ElementRef ID="r2" REF="eSc_tb_2"/><ElementRef ID="r1" REF="eSc_tb_1"/></OrderedGroup>
  </ReadingOrder>
  <Layout>
    <Page WIDTH="2000" HEIGHT="3000" PHYSICAL_IMG_NR="1" ID="eSc_dummypage_">
      <PrintSpace HPOS="0" VPOS="0" WIDTH="2000" HEIGHT="3000">
        <TextBlock ID="eSc_tb_1" HPOS="100" VPOS="100" WIDTH="800" HEIGHT="200" TAGREFS="BT1">
          <Shape><Polygon POINTS="100 100 900 100 900 300 100 300"/></Shape>
          <TextLine ID="eSc_line_1" TAGREFS="LT1" BASELINE="110 180 890 185" HPOS="110" VPOS="120"
                    WIDTH="780" HEIGHT="70">
            <Shape><Polygon POINTS="110 120 890 120 890 190 110 190"/></Shape>
            <String CONTENT="Lorem ipsum" HPOS="110" VPOS="120" WIDTH="780" HEIGHT="70"/>
          </TextLine>
        </TextBlock>
        <TextBlock ID="eSc_tb_2" HPOS="1000" VPOS="100" WIDTH="800" HEIGHT="200">
          <TextLine ID="eSc_line_2" BASELINE="1010,180 1790,180" HPOS="1010" VPOS="120" WIDTH="780" HEIGHT="70">
            <String CONTENT="dolor" HPOS="1010" VPOS="120" WIDTH="300" HEIGHT="70"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
"""


def test_alto_v2_mm10_scaled_to_the_image():
    t = from_alto(ALTO_V2_MM10, image_width=2480, image_height=3508)
    sx, sy = 2480 / 2100, 3508 / 2970
    assert [r.id for r in t.regions] == ["TB0", "TB1", "IL1"]       # ComposedBlock is transparent
    assert [r.label for r in t.regions] == ["text", "text", "picture"]
    assert [r.reading_order for r in t.regions] == [0, 1, 2]          # implicit document order
    ln = t.lines[1]
    assert ln.id == "TL1" and ln.region_id == "TB1"
    assert ln.bbox == pytest.approx([100 * sx, 200 * sy, 1900 * sx, 50 * sy])
    assert [v for p in ln.baseline for v in p] == pytest.approx([100 * sx, 245 * sy, 2000 * sx, 245 * sy])
    assert ln.text == "It was consider-"
    assert ln.words[-1].text == "consider-" and ln.words[-1].hyphen
    assert [w.id for w in ln.words] == ["S1", "S2", "S3"]
    assert ln.confidence == pytest.approx((0.99 * 2 + 0.98 * 3 + 0.7 * 9) / 14)
    # strings without IDs get generated ones; lines without IDs too
    first = t.lines[0]
    assert first.id == "line_0" and [w.id for w in first.words] == ["line_0_w0", "line_0_w1"]
    assert t.lines[2].text == "able" and t.lines[2].confidence is None
    assert [ln.reading_order for ln in t.lines] == [0, 1, 2]
    assert t.source.uri == "0001.jp2" and t.source.image_width == 2480
    assert t.source.extra["measurement_unit"] == "mm10"


def test_alto_mm10_with_dpi_and_without():
    t = from_alto(ALTO_V2_MM10, dpi=300)
    f = 300 / 254
    assert t.lines[1].bbox == pytest.approx([100 * f, 200 * f, 1900 * f, 50 * f])
    assert t.source.image_width == round(2100 * f)
    with pytest.raises(ValueError, match="mm10"):
        from_alto(ALTO_V2_MM10)


def test_alto_inch1200_with_dpi():
    data = ALTO_V2_MM10.replace(b"mm10", b"inch1200")
    t = from_alto(data, dpi=400)
    assert t.lines[1].bbox[0] == pytest.approx(100 * 400 / 1200)


def test_alto_pixel_scaled_when_image_differs():
    t = from_alto(ALTO_V3_NO_NS, image_width=500, image_height=750)
    assert t.regions[0].bbox == [5.0, 5.0, 250.0, 20.0]
    assert t.source.extra["scale"] == [0.5, 0.5]


def test_alto_v3_without_namespace_and_tags():
    t = from_alto(ALTO_V3_NO_NS)
    assert [(r.id, r.label, r.raw_label) for r in t.regions] == [
        ("b1", "section_header", "heading"), ("b2", "text", "paragraph")]
    assert t.regions[0].polygon == [[10.0, 10.0], [510.0, 10.0], [510.0, 50.0], [10.0, 50.0]]
    assert t.lines[0].confidence is None and t.lines[1].confidence == 0.5
    assert t.text == "Introduction\nText"


def test_alto_v4_escriptorium():
    t = from_alto(ALTO_V4_ESCRIPTORIUM)
    r = {x.id: x for x in t.regions}
    assert r["eSc_tb_1"].raw_label == "MainZone" and r["eSc_tb_1"].label == "text"
    assert r["eSc_tb_2"].reading_order == 0 and r["eSc_tb_1"].reading_order == 1
    ln = t.lines[0]
    assert ln.baseline == [[110.0, 180.0], [890.0, 185.0]]
    assert ln.polygon == [[110.0, 120.0], [890.0, 120.0], [890.0, 190.0], [110.0, 190.0]]
    assert ln.text == "Lorem ipsum"
    assert t.lines[1].baseline == [[1010.0, 180.0], [1790.0, 180.0]]


PAGE_2010_POINTS = b"""<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2010-03-19">
  <Metadata><Creator>x</Creator><Created>2011-01-01T00:00:00</Created><LastChange>2011-01-01T00:00:00</LastChange></Metadata>
  <Page imageFilename="00000001.tif" imageWidth="1000" imageHeight="1400">
    <ReadingOrder>
      <OrderedGroup id="g0">
        <RegionRefIndexed index="1" regionRef="r1"/>
        <RegionRefIndexed index="0" regionRef="r2"/>
      </OrderedGroup>
    </ReadingOrder>
    <TextRegion id="r1" type="paragraph">
      <Coords><Point x="10" y="300"/><Point x="900" y="300"/><Point x="900" y="400"/><Point x="10" y="400"/></Coords>
      <TextLine id="r1l1">
        <Coords><Point x="10" y="300"/><Point x="900" y="300"/><Point x="900" y="350"/><Point x="10" y="350"/></Coords>
        <Word id="r1l1w1">
          <Coords><Point x="10" y="300"/><Point x="100" y="300"/><Point x="100" y="350"/><Point x="10" y="350"/></Coords>
          <TextEquiv conf="0.9"><Unicode>Body</Unicode></TextEquiv>
        </Word>
        <Word id="r1l1w2">
          <Coords><Point x="120" y="300"/><Point x="200" y="300"/><Point x="200" y="350"/><Point x="120" y="350"/></Coords>
          <TextEquiv><Unicode>text</Unicode></TextEquiv>
        </Word>
      </TextLine>
    </TextRegion>
    <TextRegion id="r2" type="heading">
      <Coords><Point x="10" y="10"/><Point x="900" y="10"/><Point x="900" y="100"/><Point x="10" y="100"/></Coords>
      <TextLine id="r2l1">
        <Coords><Point x="10" y="10"/><Point x="900" y="10"/><Point x="900" y="100"/><Point x="10" y="100"/></Coords>
        <TextEquiv><Unicode>Heading</Unicode></TextEquiv>
      </TextLine>
    </TextRegion>
    <TableRegion id="t1">
      <Coords><Point x="10" y="500"/><Point x="900" y="500"/><Point x="900" y="900"/><Point x="10" y="900"/></Coords>
    </TableRegion>
  </Page>
</PcGts>
"""

PAGE_2013_TRANSKRIBUS = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15">
  <Metadata><Creator>Transkribus</Creator><Created>2020-01-01T00:00:00</Created><LastChange>2020-01-01T00:00:00</LastChange></Metadata>
  <Page imageFilename="p1.jpg" imageWidth="2000" imageHeight="3000">
    <TextRegion orientation="0.0" id="tr_1" custom="readingOrder {index:0;} structure {type:marginalia;}">
      <Coords points="1500,100 1900,100 1900,900 1500,900"/>
      <TextLine id="tr_1_tl_1" custom="readingOrder {index:0;}">
        <Coords points="1500,100 1900,100 1900,160 1500,160"/>
        <Baseline points="1500,150 1700,152 1900,149"/>
        <TextEquiv><Unicode>nota bene</Unicode></TextEquiv>
      </TextLine>
      <TextLine id="tr_1_tl_2" custom="readingOrder {index:1;}">
        <Coords points="1500,170 1900,170 1900,230 1500,230"/>
        <Baseline points="1500,220 1900,220"/>
        <TextEquiv><Unicode></Unicode></TextEquiv>
      </TextLine>
    </TextRegion>
    <TextRegion id="tr_2" type="page-number" custom="readingOrder {index:1;}">
      <Coords points="900,2900 1100,2900 1100,2980 900,2980"/>
    </TextRegion>
  </Page>
</PcGts>
"""


def test_page_2010_point_children_and_reading_order():
    t = from_page(PAGE_2010_POINTS)
    r = {x.id: x for x in t.regions}
    assert r["r2"].reading_order == 0 and r["r1"].reading_order == 1 and r["t1"].reading_order is None
    assert r["r2"].label == "section_header" and r["r2"].raw_label == "heading"
    assert r["t1"].label == "table" and r["t1"].raw_label == "TableRegion"
    assert r["r1"].bbox == [10.0, 300.0, 890.0, 100.0]
    body = t.lines[0]
    assert body.text == "Body text"          # no line TextEquiv: joined from the words
    assert body.words[0].confidence == 0.9 and body.words[1].confidence is None
    assert body.words[1].bbox == [120.0, 300.0, 80.0, 50.0]
    assert t.source.uri == "00000001.tif" and t.source.image_height == 1400


def test_page_2013_transkribus_custom():
    t = from_page(PAGE_2013_TRANSKRIBUS)
    assert [(r.id, r.label, r.raw_label) for r in t.regions] == [
        ("tr_1", "text", "marginalia"), ("tr_2", "page_footer", "page-number")]
    assert [r.reading_order for r in t.regions] == [0, 1]       # no ReadingOrder: document order
    assert t.lines[0].baseline == [[1500.0, 150.0], [1700.0, 152.0], [1900.0, 149.0]]
    assert t.lines[1].text == ""
    assert t.lines[0].polygon == [[1500.0, 100.0], [1900.0, 100.0], [1900.0, 160.0], [1500.0, 160.0]]


HOCR_TESSERACT = b"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
 <head>
  <title></title>
  <meta http-equiv="Content-Type" content="text/html;charset=utf-8"/>
  <meta name='ocr-system' content='tesseract 5.3.0' />
  <meta name='ocr-capabilities' content='ocr_page ocr_carea ocr_par ocr_line ocrx_word ocrp_wconf'/>
 </head>
 <body>
  <div class='ocr_page' id='page_1' title='image "scan; 01.png"; bbox 0 0 1200 1800; ppageno 0; scan_res 300 300'>
   <div class='ocr_carea' id='block_1_1' title="bbox 100 80 1100 140">
    <p class='ocr_par' id='par_1_1' lang='eng' title="bbox 100 80 1100 140">
     <span class='ocr_header' id='line_1_1' title="bbox 100 80 1100 140; baseline 0 -12; x_size 50; x_descenders 10; x_ascenders 12">
      <span class='ocrx_word' id='word_1_1' title='bbox 100 85 400 128; x_wconf 96'><strong>PREFACE</strong></span>
     </span>
    </p>
   </div>
   <div class='ocr_carea' id='block_1_2' title="bbox 100 200 1100 330">
    <p class='ocr_par' id='par_1_2' lang='eng' title="bbox 100 200 1100 260">
     <span class='ocr_line' id='line_1_2' title="bbox 100 200 1100 250; baseline 0.01 -8; x_size 40">
      <span class='ocrx_word' id='word_1_2' title='bbox 100 205 220 242; x_wconf 91'>The</span>
      <span class='ocrx_word' id='word_1_3' title='bbox 240 205 400 242; x_wconf 88'>author</span>
     </span>
    </p>
    <p class='ocr_par' id='par_1_3' lang='eng' title="bbox 100 280 1100 330">
     <span class='ocr_caption' id='line_1_3' title="bbox 100 280 600 330; baseline 0 -6">
      <span class='ocrx_word' id='word_1_4' title='bbox 100 285 300 322; x_wconf 77'><em>Fig.</em></span>
      <span class='ocrx_word' id='word_1_5' title='bbox 320 285 400 322; x_wconf 70'>1</span>
     </span>
    </p>
   </div>
   <div class='ocr_photo' id='block_1_3' title="bbox 100 400 1100 1400"></div>
  </div>
 </body>
</html>
"""

HOCR_TAG_SOUP = b"""<html><head><meta charset=utf-8><title>x</title></head><body>
<div class="ocr_page" title="bbox 0 0 800 600">
<span class="ocr_line" title="bbox 10 10 300 40"><span class="ocrx_word" title="bbox 10 10 100 40; x_wconf 50">loose</span> <span class="ocrx_word" title="bbox 110 10 300 40">line<br></span></span>
</div></body></html>"""


def test_hocr_tesseract():
    t = from_hocr(HOCR_TESSERACT)
    assert [(r.id, r.label) for r in t.regions] == [
        ("block_1_1", "text"), ("block_1_2", "text"), ("block_1_3", "picture")]
    assert [r.reading_order for r in t.regions] == [0, 1, 2]
    assert [ln.id for ln in t.lines] == ["line_1_1", "line_1_2", "line_1_3"]
    assert [ln.row for ln in t.lines] == [0, 0, 1]
    assert t.lines[0].text == "PREFACE" and t.lines[0].words[0].confidence == 0.96
    assert t.lines[1].baseline == [[100.0, 242.0], [1100.0, 252.0]]
    assert t.lines[2].text == "Fig. 1" and t.lines[2].region_id == "block_1_2"
    assert t.source.uri == "scan; 01.png" and t.source.image_width == 1200
    assert t.language == "en"


def test_hocr_tag_soup_html():
    t = from_hocr(HOCR_TAG_SOUP)
    assert t.regions == []
    assert len(t.lines) == 1 and t.lines[0].region_id is None
    assert t.lines[0].text == "loose line"
    assert t.lines[0].words[0].id == "line_0_w0"
    assert t.lines[0].words[1].confidence is None


def test_page_region_without_coords_keeps_its_lines():
    data = b"""<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">
      <Metadata/><Page imageFilename="a.png" imageWidth="100" imageHeight="100">
        <TextRegion id="r">
          <TextLine id="l"><Coords points="10,10 50,10 50,20 10,20"/><TextEquiv><Unicode>hi</Unicode></TextEquiv></TextLine>
        </TextRegion>
      </Page></PcGts>"""
    t = from_page(data)
    assert t.regions[0].bbox == [10.0, 10.0, 40.0, 10.0]
    assert t.lines[0].region_id == "r" and t.text == "hi"
