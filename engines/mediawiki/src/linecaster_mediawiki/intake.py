"""``linecaster-mediawiki intake``: a wiki's pages-articles dump into a site folder (``Site``).

    linecaster-mediawiki intake SITE DUMP [DUMP ...] [--siteinfo siteinfo.json] [--namespace 106 ...]

Reads the dump's Template (10) and Module (828) namespaces and any namespaces given (a ProofreadPage Index namespace,
for the Index pages' style sheets and page lists) into wikitextprocessor's database ``SITE/pages.db``, with the style
sheets wikitextprocessor's own dump parser leaves out (content model ``sanitized-css``: TemplateStyles), and writes the
wiki's namespaces in wikitextprocessor's format. The namespaces come from ``--siteinfo`` (the API's
``meta=siteinfo&siprop=general|namespaces|namespacealiases|interwikimap``, which also has the aliases and the
interwiki map) or else from the dump's own ``<siteinfo>`` header (names only). Nothing is fetched.
"""
from __future__ import annotations

import argparse
import bz2
import gzip
import json
import shutil
from pathlib import Path

from .site import CANONICAL

TEMPLATE, MODULE = 10, 828


def _open(path: Path):
    return bz2.open(path, "rb") if path.suffix == ".bz2" else gzip.open(path, "rb") if path.suffix == ".gz" \
        else open(path, "rb")


def siteinfo_from_dump(path: Path) -> dict:
    """The dump's ``<siteinfo>`` header as the API's siteinfo (formatversion 2): general (lang from dbname),
    namespaces (no aliases)."""
    from lxml import etree

    with _open(path) as f:
        for _, el in etree.iterparse(f, events=("end",)):
            if etree.QName(el).localname != "siteinfo":
                continue
            ns = {etree.QName(c).localname: c for c in el}
            dbname = ns["dbname"].text if "dbname" in ns else ""
            general = {"sitename": ns["sitename"].text if "sitename" in ns else "", "dbname": dbname,
                       "lang": dbname.split("wiki")[0] or "en"}
            namespaces = {}
            for n in ns["namespaces"]:
                key = int(n.get("key"))
                namespaces[str(key)] = {"id": key, "name": n.text or "", "canonical": CANONICAL.get(key, n.text or ""),
                                        "case": n.get("case"), "content": key == 0}
            return {"general": general, "namespaces": namespaces, "namespacealiases": [], "interwikimap": []}
    raise ValueError(f"{path}: no <siteinfo>")


def normalized_siteinfo(data: dict) -> dict:
    """The API's siteinfo (formatversion 1 or 2, with or without ``query``) as formatversion 2."""
    q = data.get("query", data)
    namespaces = {}
    for k, v in q["namespaces"].items():
        i = int(k)
        namespaces[str(i)] = {"id": i, "name": v.get("name", v.get("*", "")), "canonical": v.get("canonical", ""),
                              "case": v.get("case"), "content": bool(v.get("content")),
                              "subpages": bool(v.get("subpages"))}
    aliases = [{"id": int(a["id"]), "alias": a.get("alias", a.get("*"))} for a in q.get("namespacealiases", [])]
    return {"general": q.get("general", {}), "namespaces": namespaces, "namespacealiases": aliases,
            "interwikimap": q.get("interwikimap", [])}


def wtp_namespaces(siteinfo: dict) -> dict:
    """The namespaces in wikitextprocessor's format: by its canonical key, with id, local name, aliases."""
    aliases: dict[int, list[str]] = {}
    for a in siteinfo["namespacealiases"]:
        aliases.setdefault(a["id"], []).append(a["alias"])
    out = {}
    for v in siteinfo["namespaces"].values():
        i = v["id"]
        key = CANONICAL.get(i) or v.get("canonical") or v["name"]
        out[key] = {"id": i, "name": v["name"] or "Main", "subpages": bool(v.get("subpages")),
                    "content": bool(v.get("content")), "aliases": aliases.get(i, []),
                    "issubject": i % 2 == 0, "istalk": i >= 0 and i % 2 == 1}
    return out


def intake(folder: Path, dumps: list[Path], siteinfo: Path | None = None, namespaces: tuple[int, ...] = (),
           texvc: bool = True) -> Path:
    """Writes the site folder ``folder`` from ``dumps``, with MediaWiki's TeX checker unless not ``texvc``
    (``linecaster_mediawiki.texvc``: Node and npm); returns it."""
    import wikitextprocessor
    from wikitextprocessor.dumpparser import process_dump

    folder.mkdir(parents=True, exist_ok=True)
    info = normalized_siteinfo(json.loads(siteinfo.read_text())) if siteinfo else siteinfo_from_dump(dumps[0])
    (folder / "siteinfo.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    (folder / "namespaces.json").write_text(json.dumps(wtp_namespaces(info), indent=1, ensure_ascii=False),
                                            encoding="utf-8")
    lang = info["general"].get("lang", "en")
    loc = Path(wikitextprocessor.__file__).parent / "data" / lang / "localization.json"
    shutil.copy(loc if loc.exists() else loc.parent.parent / "en" / "localization.json", folder / "localization.json")
    from .site import open_context

    w = open_context(folder, lang)                 # its own: Site.wtp()'s, which readers share, stays open
    for dump in dumps:
        process_dump(w, str(dump), {TEMPLATE, MODULE, *namespaces})
        style_sheets(w, dump, {TEMPLATE, *namespaces})
    w.close_db_conn()
    if texvc:
        from .texvc import install

        install(folder)
    return folder


def style_sheets(w, dump: Path, namespaces: set[int]) -> int:
    """The dump's style sheets (content model ``sanitized-css``: TemplateStyles' sheets, an Index's styles.css) into
    the database: wikitextprocessor's dump parser leaves them out. Returns how many."""
    from lxml import etree

    n = 0
    with _open(dump) as f:
        for _, page in etree.iterparse(f, tag="{*}page"):
            if page.findtext("{*}revision/{*}model", "") in ("sanitized-css", "css") \
                    and int(page.findtext("{*}ns", "0")) in namespaces:
                w.add_page(page.findtext("{*}title", ""), int(page.findtext("{*}ns", "0")),
                           body=page.findtext("{*}revision/{*}text", ""), model="sanitized-css")
                n += 1
            page.clear(keep_tail=True)
    w.db_conn.commit()
    return n


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="linecaster-mediawiki", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    it = sub.add_parser("intake", help="a wiki's dump into a site folder")
    it.add_argument("site", type=Path)
    it.add_argument("dumps", type=Path, nargs="+")
    it.add_argument("--siteinfo", type=Path, help="the API's siteinfo JSON (with namespace aliases)")
    it.add_argument("--namespace", type=int, action="append", default=[],
                    help="a further namespace to read (a ProofreadPage Index namespace: its style sheets)")
    it.add_argument("--no-texvc", action="store_true", help="without MediaWiki's TeX checker (formulas as written)")
    tv = sub.add_parser("texvc", help="MediaWiki's TeX checker into an existing site folder")
    tv.add_argument("site", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "intake":
        print(intake(a.site, a.dumps, a.siteinfo, tuple(a.namespace), texvc=not a.no_texvc))
    elif a.cmd == "texvc":
        from .texvc import install

        print(install(a.site))


if __name__ == "__main__":
    main()
