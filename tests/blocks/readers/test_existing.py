"""The listings of ``linecaster.blocks.readers.existing.ExistingImages``: an item's folder listed once; a listing that
hangs is given up after its timeout (the item has nothing to reuse, a warning, a stat), and on an async filesystem
(object storage) fsspec cancels it on its IO loop, so neither a thread nor the loop stays busy and the next listing
works; a listing that fails is the same, counted apart."""
import asyncio
import threading
import time

from datatrove.io import DataFolder
from fsspec.asyn import AsyncFileSystem
from loguru import logger

from linecaster.blocks.readers.existing import ExistingImages


class HangingAsyncFS(AsyncFileSystem):
    """An async filesystem (as s3fs is) whose listing of a folder named ``hang`` never returns by itself."""

    cachable = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cancelled = threading.Event()

    async def _ls(self, path, detail=True, **kwargs):
        if path.rstrip("/").endswith("hang"):
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        return [{"name": f"{path}/{path.rsplit('/', 1)[-1]}_0001.png", "size": 3, "type": "file"}]


def warnings_of(fn):
    lines = []
    sink = logger.add(lines.append, level="WARNING")
    try:
        return fn(), lines
    finally:
        logger.remove(sink)


def test_a_hung_listing_on_object_storage_is_cancelled_and_the_next_one_works():
    fs = HangingAsyncFS()
    found = ExistingImages(DataFolder("root", fs=fs), listing_timeout=0.5)
    counted = []
    started = time.monotonic()
    copy, lines = warnings_of(lambda: found.get("hang", "hang_0001", counted.append))
    assert copy is None and time.monotonic() - started < 2
    assert counted == ["reuse_listing_timeouts"] and len(lines) == 1 and "root/hang" in lines[0]
    assert fs.cancelled.wait(3)                          # fsspec cancelled the listing on its loop: nothing left there
    assert found.get("ok", "ok_0001", counted.append)[1:] == (3, "png")   # the loop serves the next listing
    assert counted == ["reuse_listing_timeouts"]
    assert found.get("hang", "hang_0002") is None and counted == ["reuse_listing_timeouts"]   # listed once per item


def test_a_listing_that_fails_counts_as_nothing_to_reuse(tmp_path):
    class Failing(DataFolder):
        cachable = False

        def ls(self, path, detail=True, **kwargs):
            raise PermissionError("access denied")

    counted = []
    copy, lines = warnings_of(lambda: ExistingImages(Failing(str(tmp_path))).get("b", "b_0001", counted.append))
    assert copy is None and counted == ["reuse_listing_errors"]
    assert len(lines) == 1 and "failed after" in lines[0] and "access denied" in lines[0]
    assert ExistingImages(str(tmp_path)).get("missing", "missing_0001") is None    # no folder: nothing, no warning
