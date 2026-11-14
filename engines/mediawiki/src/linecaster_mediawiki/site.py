"""A wiki as the importer sees it: a folder written by ``linecaster-mediawiki intake`` that holds wikitextprocessor's
database of the wiki's pages (its templates, Lua modules, style sheets and ProofreadPage Index pages), the wiki's
namespaces in wikitextprocessor's format, and its siteinfo.

``Site.wtp()`` gives a wikitextprocessor context set up for the wiki, with MediaWiki's extension tags registered
(ProofreadPage, Cite, Poem, Score, Math, Chem, Gallery, Labeled Section Transclusion, TemplateStyles, ...) and one gap
of wikitextprocessor filled: ``mw.title``'s ``file`` table, which it leaves unimplemented, answers that a file
exists (1000 x 1000 pixels; a module that asks, such as a figure template, needs the size only for layout).

The importer reads no network: wikitextprocessor would fetch the interwiki map from the wiki's live API when it
takes in a dump, and ask Wikidata when a Lua module does; here the interwiki map is the siteinfo's (the API's
``siprop=interwikimap``, where the siteinfo given to ``intake`` has it) and Wikidata answers as a wiki without
Wikibase does: nothing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

#: MediaWiki's extension tags that wikitextprocessor does not know, with how they nest
EXTENSION_TAGS = {
    "poem": {"parents": ["flow"], "content": ["flow"]},
    "pages": {"parents": ["flow"], "no-end-tag": True, "content": []},
    "pagelist": {"parents": ["flow"], "no-end-tag": True, "content": []},
    "pagequality": {"parents": ["flow"], "no-end-tag": True, "content": []},
    "section": {"parents": ["phrasing"], "no-end-tag": True, "content": []},
    "score": {"parents": ["flow"], "content": ["phrasing"]},
    "chem": {"parents": ["phrasing"], "content": ["phrasing"]},
    "ce": {"parents": ["phrasing"], "content": ["phrasing"]},
    "hiero": {"parents": ["phrasing"], "content": ["phrasing"]},
    "gallery": {"parents": ["flow"], "content": ["phrasing"]},
    "imagemap": {"parents": ["flow"], "content": ["phrasing"]},
    "syntaxhighlight": {"parents": ["flow"], "content": ["phrasing"]},
    "source": {"parents": ["flow"], "content": ["phrasing"]},
    "timeline": {"parents": ["flow"], "content": ["phrasing"]},
    "indicator": {"parents": ["flow"], "content": ["phrasing"]},
    "templatedata": {"parents": ["flow"], "content": ["phrasing"]},
    "charinsert": {"parents": ["phrasing"], "content": ["phrasing"]},
}
#: MediaWiki's canonical names for the namespaces wikitextprocessor looks up by name, by id
CANONICAL = {-2: "Media", -1: "Special", 0: "Main", 1: "Talk", 2: "User", 3: "User talk", 4: "Project",
             5: "Project talk", 6: "File", 7: "File talk", 8: "MediaWiki", 9: "MediaWiki talk", 10: "Template",
             11: "Template talk", 12: "Help", 13: "Help talk", 14: "Category", 15: "Category talk", 828: "Module",
             829: "Module talk"}
FILE_STUB = "file = ns.id == 6 and {exists = true, width = 1000, height = 1000} or nil,"
_CONTEXTS: dict[Path, object] = {}


@dataclass(frozen=True)
class Site:
    """A wiki prepared by ``intake``: ``folder`` holds ``pages.db``, ``namespaces.json``, ``localization.json`` and
    ``siteinfo.json``."""

    folder: Path

    @cached_property
    def siteinfo(self) -> dict:
        return json.loads((Path(self.folder) / "siteinfo.json").read_text(encoding="utf-8"))

    @cached_property
    def lang(self) -> str:
        return self.siteinfo.get("general", {}).get("lang", "en")

    def names(self, namespace: int) -> set[str]:
        """The namespace's local name, canonical name and aliases, lowercase."""
        ns = self.siteinfo["namespaces"].get(str(namespace), {})
        found = {ns.get("name", ""), ns.get("canonical", ""), CANONICAL.get(namespace, "")}
        found |= {a["alias"] for a in self.siteinfo.get("namespacealiases", []) if a["id"] == namespace}
        return {n.lower() for n in found if n}

    @cached_property
    def file_prefix(self) -> re.Pattern:
        """A link title that names a file (the File namespace, or Media)."""
        names = "|".join(re.escape(n) for n in sorted(self.names(6) | self.names(-2), key=len, reverse=True))
        return re.compile(rf"^\s*:?\s*(?:{names})\s*:", re.I)

    @cached_property
    def hidden_link_prefix(self) -> re.Pattern:
        """A link title that prints nothing where it stands: a category (without a leading colon) or an interwiki
        language link."""
        names = "|".join(re.escape(n) for n in sorted(self.names(14), key=len, reverse=True))
        return re.compile(rf"^\s*(?:{names})\s*:", re.I)

    def wtp(self):
        """wikitextprocessor for this wiki, one per process."""
        key = Path(self.folder).resolve()
        if key not in _CONTEXTS:
            _CONTEXTS[key] = open_context(key, self.lang)
        return _CONTEXTS[key]


class _Offline:
    """wikitextprocessor's Wikidata session, answering as a wiki without Wikibase: nothing found, no request."""

    class _Answer:
        ok, status_code, text = False, 503, "offline: the importer reads no network"

        @staticmethod
        def json() -> dict:
            return {}

    def get(self, *args, **kwargs):
        return self._Answer()

    def close(self) -> None:
        pass


def _offline(siteinfo: dict) -> None:
    """wikitextprocessor makes no network request: its interwiki map is the site's (siteinfo's ``interwikimap``,
    else none), and Wikidata answers nothing."""
    from wikitextprocessor import interwiki, wikidata

    interwiki.get_interwiki_data = lambda wtp: list(siteinfo.get("interwikimap", []))
    wikidata.init_wikidata_session = lambda wtp: setattr(wtp, "wikidata_session", _Offline())


def open_context(folder: Path, lang: str):
    """A new wikitextprocessor context for the site in ``folder``, offline (``Site.wtp()`` keeps one per process)."""
    from wikitextprocessor import Wtp, luaexec

    _offline(json.loads((folder / "siteinfo.json").read_text(encoding="utf-8")))
    loader = luaexec.lua_loader

    def lua_loader(ctx, modname):
        data = loader(ctx, modname)
        if modname.strip() == "mw_title" and data:
            data = data.replace("file = nil,", FILE_STUB)
        return data

    luaexec.lua_loader = lua_loader

    class SiteWtp(Wtp):
        def init_data_folder(self) -> None:
            self.data_folder = folder

    return SiteWtp(db_path=folder / "pages.db", lang_code=lang, project="wikisource", quiet=True,
                   extension_tags=EXTENSION_TAGS)
