"""The taggers (``linecaster.engines.tagging``): the geometry tagger's rules, each decision with its evidence and
nothing recorded where the evidence does not decide; the model tagger's questions from the vocabularies, its panel
and rules, its cache and its review items, against a fake chat server (no model, no network)."""
import base64
import io
import json
import math

import numpy as np
import pytest
from PIL import Image

from linecaster.data import Annotator, Line, Transcription
from linecaster.engines import ChatTaggingEngine, GeometryTaggingEngine
from linecaster.engines.tagging import line_measure, min_area_rect, parse_answer, question, settle
from linecaster.errors import PipelineConfigError, ServerError
from linecaster.testing import check_engine, sample_layout, sample_page
from linecaster.testing.chat import completion, fake_chat_server


def _page(regions=(), lines=(), direction=None) -> Transcription:
    """A transcription: ``regions`` as (id, role, box), ``lines`` as (id, region, fields)."""
    t = Transcription()
    a = t.add_annotator(Annotator(step="layout", name="test"))
    for rid, role, box in regions:
        t.add_region(a, rid, box=list(box), role=role)
    for lid, region, fields in lines:
        t.add_line(a, lid, region=region, **fields)
    if direction:
        t.classify(a, "", "direction", direction)
    return t


def _level(x, y, w, h):
    return {"box": [x, y, w, h], "baseline": [[x, y + h * 0.8], [x + w, y + h * 0.8]]}


def _tilted(x, y, w, h, degrees):
    r = math.radians(degrees)
    return {"box": [x, y, w, h], "baseline": [[x, y], [x + w * math.cos(r), y + w * math.sin(r)]]}


def _tags(t, scheme):
    return {c.target: c.value for c in t.classifications if c.scheme == scheme}


# ------------------------------------------------------------------------------------------------ geometry

def test_min_area_rect_finds_a_tilted_line():
    r = math.radians(12)
    u, v = np.array([math.cos(r), math.sin(r)]), np.array([-math.sin(r), math.cos(r)])
    corners = [p * 1.0 for p in (np.zeros(2), 300 * u, 300 * u + 30 * v, 30 * v)]
    angle, long, short = min_area_rect(corners)
    assert angle == pytest.approx(12, abs=0.01) and long == pytest.approx(300) and short == pytest.approx(30)
    assert min_area_rect([[0, 0], [1, 1], [2, 2]]) is None


def test_rotated_by_baseline_polygon_and_direction():
    t = _page(regions=[("r", "paragraph", (0, 0, 1000, 1000))], lines=[
        ("tilted", "r", _tilted(0, 0, 400, 30, 10)),
        ("level", "r", _tilted(0, 100, 400, 30, 2)),
        ("upright", "r", _tilted(0, 200, 400, 30, 90)),
        ("box", "r", {"box": [0, 300, 400, 30]}),
        ("poly", "r", {"polygon": [[0, 400], [400, 470], [395, 500], [-5, 430]]}),
        ("glyph", "r", {"polygon": [[0, 600], [20, 600], [20, 630], [0, 630]]}),
        ("vertical", "r", {"box": [900, 0, 30, 400]}),
    ])
    t.classify(0, "vertical", "direction", "vertical-rl")
    GeometryTaggingEngine(schemes=["rotated"])(None, t)
    assert _tags(t, "rotated") == {"tilted": "yes", "level": "no", "upright": "yes", "poly": "yes",
                                   "vertical": "yes"}
    a = t.annotators[-1]
    assert a.kind == "rule" and a.step == "tagging" and a.engine == "tagging.geometry.v1"
    assert a.measurements["undecided"] == {"rotated": 2} and a.measurements["tagged"]["rotated"] == {"no": 1, "yes": 4}
    evidence = t.outputs[-1]
    assert evidence.format == "json" and evidence.content["lines"]["tilted"]["source"] == "baseline"
    assert evidence.content["lines"]["poly"]["source"] == "polygon"
    assert all(c.output == len(t.outputs) - 1 for c in t.classifications if c.scheme == "rotated")


def test_decide_no_off_records_only_yes():
    t = _page(lines=[("a", None, _tilted(0, 0, 400, 30, 10)), ("b", None, _level(0, 100, 400, 30))])
    GeometryTaggingEngine(schemes=["rotated"], decide_no=False)(None, t)
    assert _tags(t, "rotated") == {"a": "yes"}
    assert t.annotators[-1].measurements["undecided"] == {"rotated": 1}


def test_tiny_against_the_body_lines_median():
    lines = [(f"b{k}", "body", _level(0, 50 * k, 800, 40)) for k in range(6)]
    lines += [("note", "notes", _level(0, 400, 800, 22)), ("head", "top", _level(0, 0, 800, 32))]
    t = _page(regions=[("body", "paragraph", (0, 0, 800, 300)), ("notes", "footnote", (0, 400, 800, 30)),
                       ("top", "header", (0, 0, 800, 40))], lines=lines)
    GeometryTaggingEngine(schemes=["tiny"])(None, t)
    tags = _tags(t, "tiny")
    assert tags["note"] == "yes" and tags["head"] == "no" and tags["b0"] == "no"
    a = t.annotators[-1]
    assert a.measurements["body_line_height"] == pytest.approx(40, abs=1)
    assert t.outputs[-1].content["lines"]["note"]["ratio"] < 0.6


def test_tiny_decides_nothing_without_enough_body_lines():
    t = _page(regions=[("body", "paragraph", (0, 0, 800, 300))],
              lines=[(f"b{k}", "body", _level(0, 50 * k, 800, 40)) for k in range(3)])
    GeometryTaggingEngine(schemes=["tiny"])(None, t)
    assert _tags(t, "tiny") == {} and t.annotators[-1].measurements["undecided"] == {"tiny": 3}
    assert not t.outputs or "body_line_height" not in t.outputs[-1].content


def test_multi_column_from_regions_side_by_side():
    t = _page(regions=[("title", "title", (50, 0, 900, 80)), ("left", "paragraph", (50, 100, 430, 800)),
                       ("right", "paragraph", (520, 120, 430, 600)), ("end", "paragraph", (50, 950, 400, 40)),
                       ("rule", "separator", (490, 100, 5, 800))])
    GeometryTaggingEngine(schemes=["multi_column"])(None, t)
    assert _tags(t, "multi_column") == {"title": "no", "left": "yes", "right": "yes"}
    assert t.outputs[-1].content["regions"]["left"]["beside"] == ["right"]
    assert t.annotators[-1].measurements["undecided"] == {"multi_column": 1}


def test_multi_column_follows_the_writing_direction():
    # vertical-rl: the page's columns are bands one above the other
    t = _page(regions=[("upper", "paragraph", (100, 50, 800, 400)), ("lower", "paragraph", (120, 500, 760, 400))],
              direction="vertical-rl")
    GeometryTaggingEngine(schemes=["multi_column"])(None, t)
    assert _tags(t, "multi_column") == {"upper": "yes", "lower": "yes"}


def test_line_measure_reads_height_across_the_tilt():
    m = line_measure(Line(**{"annotator": 0, "id": "l", **_tilted(0, 0, 400, 30, 30),
                             "polygon": _rect(0, 0, 400, 30, 30)}), False, 3.0)
    assert m["tilt"] == pytest.approx(30, abs=0.1) and m["height"] == pytest.approx(30, abs=0.5)


def _rect(x, y, w, h, degrees):
    r = math.radians(degrees)
    u, v = np.array([math.cos(r), math.sin(r)]), np.array([-math.sin(r), math.cos(r)])
    o = np.array([x, y], dtype=float)
    return [list(p) for p in (o, o + w * u, o + w * u + h * v, o + h * v)]



def test_the_geometry_tagger_conforms():
    out = check_engine(GeometryTaggingEngine)
    assert _tags(out, "rotated") and set(_tags(out, "rotated").values()) == {"no"}


# ------------------------------------------------------------------------------------------------ the panel

def test_settle_rules():
    assert settle("first_with_referee", {"a": "yes", "b": "yes"}) == ("yes", "a", "agreed")
    assert settle("first_with_referee", {"a": "yes", "b": "no"}) == (None, None, "undecided")
    assert settle("first_with_referee", {"a": "yes", "b": "no", "c": "yes"}) == ("yes", "a", "referee")
    assert settle("first_with_referee", {"a": "yes", "b": "no", "c": "no"}) == (None, None, "undecided")
    assert settle("first_with_referee", {"a": None, "b": "no", "c": "no"}) == ("no", "b", "referee")
    assert settle("majority", {"a": "yes", "b": "no", "c": "no"}) == ("no", "b", "majority")
    assert settle("majority", {"a": "yes", "b": None, "c": None}) == (None, None, "undecided")
    assert settle("first", {"a": "no", "b": "yes"}) == ("no", "a", "first")
    assert settle("first", {"a": None, "b": "yes"}) == (None, None, "undecided")


def test_parse_answer():
    answers = {"degraded": "yes", "not_degraded": "no"}
    assert parse_answer('{"reason": "blurred", "answer": "degraded"}', answers) == ("degraded", "yes", "blurred")
    assert parse_answer('```json\n{"reason": "clean", "answer": "Not_Degraded"}\n```', answers)[1] == "no"
    assert parse_answer('{"reason": "x", "answer": "cannot_tell"}', answers) == ("cannot_tell", None, "x")
    assert parse_answer('the "answer": "degraded" since', answers)[1] == "yes"
    assert parse_answer("yes", answers) == (None, None, None)


def test_the_question_is_generated_from_the_vocabulary():
    from linecaster.catalog import catalog

    v = catalog().vocabulary("rotated")
    q = question(v, "line", ["page", "crop"])
    assert v.values["yes"].definition in q and all(x in q for x in v.values["yes"].does_not_count)
    assert "one of: rotated, not_rotated, cannot_tell, not_here" in q and "red box" in q
    assert q.index('"reason"') < q.index('"answer"')
    page = question(v, "page", ["page"])
    assert "not_here" not in page and "red box" not in page
    roles = question(catalog().vocabulary("production"), "region", ["crop"])
    assert "printed:" in roles and "born_digital:" in roles and "The image shows that region enlarged" in roles


def _reply(answers):
    """A fake server's answer: ``answers`` maps a served model to its answer (or a function of the request)."""
    def answer(body):
        given = answers[body["model"]]
        out = given(body) if callable(given) else given
        if isinstance(out, dict):
            return out
        return json.dumps({"reason": f"{body['model']} looked", "answer": out})
    return answer


def _engine(url, cache_dir, a="degraded", b="degraded", referee=None, **options):
    members = [{"model": "a", "url": url, "revision": "1"}, {"model": "b", "url": url}]
    return ChatTaggingEngine(schemes=["degraded"], panel=members,
                             referee={"model": "c", "url": url} if referee else None,
                             cache_dir=str(cache_dir), concurrency=1, **options)


def _sample():
    return np.array(sample_page()), sample_layout(text=True)


def test_the_panel_agrees(tmp_path):
    with fake_chat_server(_reply({"a": "degraded", "b": "degraded"})) as server:
        image, t = _sample()
        e = _engine(server.url, tmp_path)
        e.load()
        e(image, t, page="p1")
    assert _tags(t, "degraded") == {"text_0": "yes"}
    a = t.annotators[-1]
    assert a.kind == "model" and a.step == "tagging" and a.name == "a + b" and a.engine == "tagging.chat.v1"
    assert a.settings["panel"][0] == {"model": "a", "revision": "1", "max_tokens": 512, "temperature": 0.0}
    assert "url" not in json.dumps(a.settings) and a.settings["settle"] == {"degraded": "first_with_referee"}
    assert a.settings["vocabularies"]["degraded"].startswith("sha256:")
    assert a.measurements["agreed"] == 1 and a.measurements["asked"] == {"a": 1, "b": 1}
    outs = t.outputs[-2:]
    assert [o.settings["member"] for o in outs] == ["a", "b"] and [o.kept for o in outs] == [True, False]
    c = next(c for c in t.classifications if c.scheme == "degraded")
    assert t.outputs[c.output].settings == {"member": "a", "target": "text_0", "scheme": "degraded"}
    body = server.requests[0]
    parts = body["messages"][0]["content"]
    assert [p["type"] for p in parts] == ["image_url", "image_url", "text"] and body["temperature"] == 0.0
    crop = Image.open(io.BytesIO(base64.b64decode(parts[1]["image_url"]["url"].split(",", 1)[1])))
    assert (255, 0, 0) in {crop.getpixel((x, y)) for x in range(crop.width) for y in range(0, crop.height, 4)}


def test_a_split_goes_to_the_referee_and_the_rule(tmp_path):
    with fake_chat_server(_reply({"a": "degraded", "b": "not_degraded", "c": "degraded"})) as server:
        image, t = _sample()
        _engine(server.url, tmp_path, referee=True)(image, t)
        assert len(server.requests) == 3
    assert _tags(t, "degraded") == {"text_0": "yes"} and t.annotators[-1].measurements["settled"] == 1
    assert [o.settings["member"] for o in t.outputs[-3:]] == ["a", "b", "c"]


def test_the_first_rule_needs_no_referee(tmp_path):
    with fake_chat_server(_reply({"a": "not_degraded", "b": "degraded", "c": "degraded"})) as server:
        image, t = _sample()
        _engine(server.url, tmp_path, referee=True, settle={"degraded": "first"})(image, t)
        assert {r["model"] for r in server.requests} == {"a", "b"}
    assert _tags(t, "degraded") == {"text_0": "no"}


def test_the_majority_rule(tmp_path):
    with fake_chat_server(_reply({"a": "not_degraded", "b": "degraded", "c": "degraded"})) as server:
        image, t = _sample()
        _engine(server.url, tmp_path, referee=True, default_settle="majority")(image, t)
    assert _tags(t, "degraded") == {"text_0": "yes"}
    assert next(o for o in t.outputs if o.kept).settings["member"] == "b"


def test_the_undecided_are_written_for_review_and_not_recorded(tmp_path):
    with fake_chat_server(_reply({"a": "degraded", "b": "not_degraded", "c": "not_degraded"})) as server:
        image, t = _sample()
        _engine(server.url, tmp_path / "cache", referee=True, review=str(tmp_path / "review"))(image, t, page="p7")
    assert _tags(t, "degraded") == {} and t.annotators[-1].measurements["undecided"] == {"degraded": 1}
    assert not any(o.kept for o in t.outputs)
    files = list((tmp_path / "review").glob("review-*.jsonl"))
    assert len(files) == 1
    item = json.loads(files[0].read_text(encoding="utf-8"))
    assert item["schema"] == "linecaster.tagging-review/1" and item["page"] == "p7" and item["target"] == "text_0"
    assert [x["answer"] for x in item["answers"]] == ["degraded", "not_degraded", "not_degraded"]
    assert item["answers"][0]["reason"] == "a looked" and item["images"][0].startswith("data:image/png;base64,")


def test_no_answer_is_no_vote(tmp_path):
    with fake_chat_server(_reply({"a": "cannot_tell", "b": "I think it is degraded"})) as server:
        image, t = _sample()
        _engine(server.url, tmp_path)(image, t)
    assert _tags(t, "degraded") == {}


def test_answers_are_cached_by_what_was_shown(tmp_path):
    with fake_chat_server(_reply({"a": "degraded", "b": "degraded"})) as server:
        image, t = _sample()
        _engine(server.url, tmp_path)(image, t)
        assert len(server.requests) == 2
        t2 = sample_layout(text=True)
        _engine(server.url, tmp_path)(image, t2)
        assert len(server.requests) == 2
        assert t2.annotators[-1].measurements["cached"] == {"a": 1, "b": 1}
        assert _tags(t2, "degraded") == {"text_0": "yes"}
        _engine(server.url, tmp_path, crop_longest=256)(image, sample_layout(text=True))    # another image: asked
        assert len(server.requests) == 4
    assert len(list(tmp_path.glob("*/*.json"))) == 4


def test_lines_are_asked_one_question_per_line_and_scheme(tmp_path):
    with fake_chat_server(_reply({"a": "not_rotated", "b": "not_rotated"})) as server:
        image, t = _sample()
        e = ChatTaggingEngine(schemes=["rotated"], target="line", cache=False,
                              panel=[{"model": "a", "url": server.url}, {"model": "b", "url": server.url}])
        e(image, t)
        assert len(server.requests) == 2 * len(t.lines)
    assert set(_tags(t, "rotated")) == {ln.id for ln in t.lines}


def test_a_scheme_must_classify_the_target():
    e = ChatTaggingEngine(schemes=["multi_column"], target="line",
                          panel=[{"model": "a"}, {"model": "b"}])
    with pytest.raises(PipelineConfigError, match="classifies region"):
        e.load()
    with pytest.raises(PipelineConfigError, match="no vocabulary"):
        ChatTaggingEngine(schemes=["nothing"], panel=[{"model": "a"}, {"model": "b"}]).load()
    with pytest.raises(ValueError, match="settle names schemes"):
        ChatTaggingEngine(schemes=["degraded"], settle={"tiny": "first"}, panel=[{"model": "a"}, {"model": "b"}])


def test_a_member_names_a_chat_preset(tmp_path):
    from linecaster.catalog import catalog

    e = ChatTaggingEngine(schemes=["degraded"], panel=[{"preset": "lightonocr-2-1b"}, {"model": "b"}])
    e.load()
    m = e._member(e.options.panel[0])
    r = catalog().resolve("lightonocr-2-1b")
    assert m["preset"] == "lightonocr-2-1b" and m["preset_sha256"] == r.sha256
    assert m["revision"] == r.content["model"]["revision"] and "/" in m["model"]
    with pytest.raises(PipelineConfigError, match="not a chat preset"):
        ChatTaggingEngine(schemes=["degraded"], panel=[{"preset": "geometry-tags"}, {"model": "b"}]).load()


def test_a_server_that_does_not_answer_is_a_server_error(tmp_path):
    image, t = _sample()
    e = ChatTaggingEngine(schemes=["degraded"], cache=False, retries=0, timeout=2,
                          panel=[{"model": "a", "url": "http://127.0.0.1:9/v1"}, {"model": "b"}])
    with pytest.raises(ServerError):
        e(image, t)


def test_the_model_tagger_conforms(tmp_path):
    with fake_chat_server(lambda body: completion('{"reason": "r", "answer": "not_degraded"}')) as server:
        out = check_engine(ChatTaggingEngine, options={
            "schemes": ["degraded"], "cache": False,
            "panel": [{"model": "a", "url": server.url}, {"model": "b", "url": server.url}]})
    assert _tags(out, "degraded") == {"text_0": "no"}
