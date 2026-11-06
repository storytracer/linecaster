LightOnOCR-2-1B on layout regions (`RegionRecognizer` after a layout step): each region is cut from the page
scaled to LightOnOCR's 1540-px page size, 8 px around its box at that scale, and sent as it is, with the page
preset's request and sampling.

LightOnOCR-2 is trained on whole pages. On the 60-page sample with PP-DocLayoutV3 regions it loops to its token
limit on part of the region crops (page headers, footers, footnotes), and reads worse than the page preset on whole
pages (the evidence, from NOTES.md, "Region recognition with a page model"). Kept as an
experimental way to read regions with a page model; region reading wants a region-trained model
(`minicpm-ocr-1.0`).
