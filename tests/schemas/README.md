# Schemas used by the serialisation tests

| File | Source | Licence |
|------|--------|---------|
| `alto-4-4.xsd` | <https://www.loc.gov/standards/alto/v4/alto-4-4.xsd> (fetched 2026-11-03, sha256 of the original `5564fd29…702b`); the only change: the `xlink` import points to the local `xlink.xsd` | CC BY-SA 4.0 (ALTO Editorial Board; see the file's header) |
| `pagecontent-2019-07-15.xsd` | <https://www.primaresearch.org/schema/PAGE/gts/pagecontent/2019-07-15/pagecontent.xsd> (fetched 2026-11-03, unchanged, sha256 `5d7da5af…32d5`) | Apache-2.0 (PRImA Research Lab, <https://github.com/PRImA-Research-Lab/PAGE-XML>) |
| `xlink.xsd` | written for these tests: the `simpleLink` attribute group ALTO imports (the Library of Congress copy returned 404) | Apache-2.0 (this repository) |

hOCR has no schema; its tests check the structure directly.
