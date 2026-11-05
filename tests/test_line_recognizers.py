# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "linecaster",
#     "linecaster-paddlex",
#     "linecaster-tesseract",
#     # PaddleX pins OpenCV's GUI build; this stub swaps in the headless build of the same version
#     "opencv-contrib-python",
#     "pytest>=8",
# ]
#
# [tool.uv]
# # the versions squiddleocr's goldens were recorded with (numerics: recognition, ONNX Runtime, CUDA, decoding);
# # the same list in every script (tests/test_scripts.py)
# constraint-dependencies = [
#     "lightning==2.6.6",
#     "onnxruntime-gpu==1.29.0",
#     "pillow==12.3.0",
#     "transformers==5.12.1",
#     "tokenizers==0.22.2",
#     "nvidia-cublas==13.1.1.3",
#     "nvidia-cuda-nvrtc==13.0.88",
#     "nvidia-cuda-runtime==13.0.96",
#     "nvidia-cudnn-cu13==9.24.0.43",
#     "nvidia-cufft==12.0.0.61",
#     "nvidia-curand==10.4.0.35",
#     "scipy==1.15.3",
#     "scikit-image==0.25.2",
# ]
#
# [tool.uv.sources]
# linecaster = { path = "..", editable = true }
# linecaster-paddlex = { path = "../engines/paddlex", editable = true }
# linecaster-tesseract = { path = "../engines/tesseract", editable = true }
# opencv-contrib-python = { path = "../stubs/opencv-contrib-python" }
# ///
"""The PaddleX and Tesseract line recognizers' geometry, without models. Skipped in the core environment;
with the engines: ``uv run tests/test_line_recognizers.py``."""
import numpy as np
import pytest


def test_paddle_line_rectangle_corner_order():
    rec = pytest.importorskip("linecaster_paddlex.recognizer")
    box = rec.line_rectangle([[10, 20], [110, 20], [110, 50], [10, 50]])
    assert box.tolist() == [[10, 20], [110, 20], [110, 50], [10, 50]]


def test_paddle_crop_line_is_upright():
    rec = pytest.importorskip("linecaster_paddlex.recognizer")
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    crop = rec.crop_line(image, rec.line_rectangle([[10, 20], [110, 20], [110, 50], [10, 50]]))
    assert crop.shape[:2] == (30, 100)


def test_paddle_words_follow_ctc_columns():
    rec = pytest.importorskip("linecaster_paddlex.recognizer")
    text = "ab cd"
    # 10 columns over a 100 px line: a=0 b=1 space=2 c=6 d=7
    info = [10, [["a", "b"], [" "], ["c", "d"]], [[0, 1], [2], [6, 7]], ["en&num", "symbol", "en&num"]]
    box = np.array([[0, 0], [100, 0], [100, 20], [0, 20]], dtype=np.float32)
    words = rec.line_words(text, info, box, "l0")
    assert [w.text for w in words] == ["ab", "cd"]
    assert [w.bbox for w in words] == [pytest.approx([0, 0, 20, 20]), pytest.approx([60, 0, 20, 20])]
    assert all(w.id.startswith("l0_w") for w in words)


def test_paddle_words_need_one_column_per_character():
    rec = pytest.importorskip("linecaster_paddlex.recognizer")
    box = np.array([[0, 0], [100, 0], [100, 20], [0, 20]], dtype=np.float32)
    assert rec.line_words("abc", [10, [["a"]], [[0]], ["en&num"]], box, "l0") == []


def test_tesseract_crop_masks_outside_the_polygon():
    tess = pytest.importorskip("linecaster_tesseract.recognizer")
    image = np.zeros((100, 200), dtype=np.uint8)
    crop, dx, dy = tess.crop_line(image, [[20, 20], [120, 20], [120, 40], [20, 40]], pad=4)
    assert (dx, dy) == (16, 16) and crop.shape == (28, 108)
    assert crop[0, 0] == 255 and crop[10, 10] == 0   # padding white, inside the polygon untouched


def test_tessdata_languages_and_commits():
    models = pytest.importorskip("linecaster_tesseract.models")
    assert set(models.TESSDATA) == {"best", "fast"}
    assert all(len(td.commit) == 40 for td in models.TESSDATA.values())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
