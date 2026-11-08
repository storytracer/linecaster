"""Proxy block markers (linecaster.net.proxy_blocks): written once, never overwritten, read by the other workers."""
import json

from linecaster.net.proxy_blocks import ProxyBlocks, proxy_id

HOUR = 3600.0


def test_proxy_id_leaves_out_scheme_and_credentials():
    assert proxy_id("http://user:secret@10.1.2.3:8080") == proxy_id("10.1.2.3:8080") == proxy_id("HTTP://10.1.2.3:8080/")
    assert proxy_id("10.1.2.3:8080") != proxy_id("10.1.2.3:8081")


def test_a_marker_is_written_once_and_read_by_the_others(tmp_path):
    one, other = ProxyBlocks(str(tmp_path)), ProxyBlocks(str(tmp_path))
    first = one.write("lccn.loc.gov", "http://u:p@10.0.0.1:80", 72 * HOUR, status="200-html")
    second = one.write("lccn.loc.gov", "http://u:p@10.0.0.1:80", HOUR)
    assert first != second                                     # a new block is a new marker, never an overwrite
    assert json.loads((tmp_path / first).read_text())["ttl"] == 72 * HOUR
    assert "secret" not in first and "u:p" not in (tmp_path / first).read_text()
    assert one.live("lccn.loc.gov") == {}                      # its own blocks it knows already
    live = other.live("lccn.loc.gov")
    assert list(live) == [proxy_id("10.0.0.1:80")] and 72 * HOUR - 60 < live[proxy_id("10.0.0.1:80")] <= 72 * HOUR
    assert other.live("www.loc.gov") == {}                     # per host


def test_expired_markers_are_deleted_by_whoever_sees_them(tmp_path):
    one, other = ProxyBlocks(str(tmp_path)), ProxyBlocks(str(tmp_path))
    gone = one.write("lccn.loc.gov", "10.0.0.1:80", -1)
    kept = one.write("lccn.loc.gov", "10.0.0.2:80", HOUR)
    assert list(other.live("lccn.loc.gov")) == [proxy_id("10.0.0.2:80")]
    assert not (tmp_path / gone).exists() and (tmp_path / kept).exists()


def test_an_unreadable_marker_is_ignored(tmp_path):
    (tmp_path / "lccn.loc.gov" / "abc").mkdir(parents=True)
    (tmp_path / "lccn.loc.gov" / "abc" / "x-1.json").write_text("not json")
    assert ProxyBlocks(str(tmp_path)).live("lccn.loc.gov") == {}
