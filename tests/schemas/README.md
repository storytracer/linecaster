# Schemas used by the serialization tests

| File | Source | License |
|------|--------|---------|
| `alto-4-4.xsd` | <https://www.loc.gov/standards/alto/v4/alto-4-4.xsd> (fetched 2026-11-03, sha256 of the original `5564fd29…702b`); the only change: the `xlink` import points to the local `xlink.xsd` | CC BY-SA 4.0 (ALTO Editorial Board; see the file's header) |
| `pagecontent-2019-07-15.xsd` | <https://www.primaresearch.org/schema/PAGE/gts/pagecontent/2019-07-15/pagecontent.xsd> (fetched 2026-11-03, unchanged, sha256 `5d7da5af…32d5`) | Apache-2.0 (PRImA Research Lab, <https://github.com/PRImA-Research-Lab/PAGE-XML>) |
| `mets-1-12-1.xsd` | <https://www.loc.gov/standards/mets/mets.xsd> (METS 1.12.1, fetched 2026-11-03, sha256 of the original `8f289c77…2a1f`); the only change: the `xlink` import points to the local `mets-xlink.xsd` | CC0 1.0 (Digital Library Federation; see the file's header) |
| `mets-xlink.xsd` | <http://www.loc.gov/standards/xlink/xlink.xsd> (the METS XLink schema v. 2, fetched 2026-11-03, unchanged, sha256 `f1f5bb60…a8a3c`) | Library of Congress (METS Editorial Board), published for use with METS |
| `page-2.json` | the JSON Schema of `linecaster.page/2` page records (`Page.model_json_schema()` at 0.7.4), frozen for the upgrade to page/3 | Apache-2.0 (this repository) |
| `xlink.xsd` | written for these tests: the `simpleLink` attribute group ALTO imports (the Library of Congress copy returned 404) | Apache-2.0 (this repository) |

hOCR has no schema; its tests check the structure directly.
