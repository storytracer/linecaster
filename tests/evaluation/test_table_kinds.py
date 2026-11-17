"""Table kinds (``linecaster.evaluation.tables``): data tables, text or numbers alike; contents lists; layout."""
from __future__ import annotations

from linecaster.data.transcription import Cell, Table
from linecaster.evaluation.tables import table_kind


def table(rows: list[list[str]]) -> Table:
    cells = [Cell(start_row=i, end_row=i + 1, start_col=j, end_col=j + 1, text=s)
             for i, row in enumerate(rows) for j, s in enumerate(row)]
    return Table(annotator=0, target="t", num_rows=len(rows), num_cols=max(len(r) for r in rows), cells=cells)


def test_text_tables_and_number_tables_are_data():
    assert table_kind(table([["NATIONAL PRESIDENT", "NATIONAL SECRETARY"], ["Sarah C. Mink", "Sarah E. Phillips"],
                             ["Emma R. Wallace", "Jennie Bross"]])) == "data"
    assert table_kind(table([["Schools", "Number of Schools", "Number of Teachers"], ["University", "1", "13"],
                             ["Provincial college", "1", "9"], ["Normal schools", "4", "31"]])) == "data"
    # labels and counts, names roughly alphabetical: still data (short labels, no page references)
    assert table_kind(table([["Sea-water", "300 to 350"], ["Boone Lick, Missouri", "450"],
                             ["Conemaugh, Pennsylvania", "300"], ["Jackson, Ohio", "213"]])) == "data"
    assert table_kind(table([["Ratio between the two", "100 : 101.2"], ["Ratio between weights", "100 : 121.5"],
                             ["Total number of flowers", "100 : 164.9"]])) == "data"


def test_contents_and_indexes_are_contents():
    toc = [["Chapter", "", "Page"], ["I", "Master Cherry and the Log", "15"], ["II", "The Laughing Log Gives", "19"],
           ["III", "Geppetto Makes His Puppet", "25"], ["IV", "The Talking Cricket Speaks", "31"]]
    assert table_kind(table(toc)) == "contents"
    old = [["Why Bees are named to be created", "Cap. j."], ["Who first taught the preparing of Bees", "cap. ij."],
           ["How Bees do naturally engender", "cap. iij."], ["Of the unperfect Bees and drones", "ca. iiij."]]
    assert table_kind(table(old)) == "contents"
    index = [["Die, black", "44"], ["Dropsy, remedies for", "45, 172"], ["Drowned persons, directions", "46"],
             ["Dysentery, remedies for", "47, 48"], ["Ear ache, remedy for", "48"]]
    assert table_kind(table(index)) == "contents"


def test_one_row_one_column_one_cell_mostly_empty_and_braces_are_layout():
    assert table_kind(table([["Executive Mansion, Washington,", "}"]])) == "layout"
    assert table_kind(table([["a"], ["b"], ["c"]])) == "layout"
    assert table_kind(table([["only"]])) == "layout"
    assert table_kind(table([["vol. 85, no. 3, pl. 15", ""], ["", ""], ["Burgess Shale Fossils", ""]])) == "layout"
    assert table_kind(table([["1639, December 4th", "}", "121½ years"], ["1761, June 5th", "", ""],
                             ["1761, June 5th", "}", "8 years"]])) == "layout"


def test_contents_in_other_scripts_and_with_other_abbreviations():
    german = [["Einleitung in die Geschichte", "S. 1"], ["Das alte Reich der Franken", "S. 17"],
              ["Die Zeit der Ottonen und Salier", "S. 45"], ["Das Ende der Staufer", "S. 88"]]
    assert table_kind(table(german)) == "contents"
    russian = [["Предисловие к первому изданию", "стр. 3"], ["Глава первая о начале", "стр. 9"],
               ["Глава вторая о пути", "стр. 21"]]
    assert table_kind(table(russian)) == "contents"
    arabic = [["مقدمة الكتاب الأولى", "٣"], ["الفصل الأول في البداية", "١٧"], ["الفصل الثاني في الطريق", "٤٥"]]
    assert table_kind(table(arabic)) == "contents"
    chinese = [["天地玄黃之說", "第1頁"], ["宇宙洪荒之論", "第12頁"], ["日月盈昃之辨", "第30頁"]]
    assert table_kind(table(chinese)) == "contents"                # titles of three characters or more
    counts = [["Schulen", "Zahl"], ["Universität", "1"], ["Gymnasium", "4"], ["Volksschule", "31"]]
    assert table_kind(table(counts)) == "data"                    # short labels with counts stay data
