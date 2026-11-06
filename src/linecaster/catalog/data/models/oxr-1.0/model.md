OXR-1.0 is SoMark's document parsing model (1.3B parameters by the card) inside a page pipeline: a D-FINE layout
model (`layout_analysis/last.pth` in this repository) finds the regions, the OXR VLM reads each region and sets the
reading order, and the vendor's `oxr` API assembles the page as Markdown and JSON. The pipeline runs in the vendor's
all-in-one image (`docker/Dockerfile.allinone` of github.com/SoMarkAI/OXR), which reads the weights from a folder;
the preset downloads this pin there. The card names no language list. License: the "OXR License" (copied as
`upstream/c708407f9d2b4df658f2543d9132b62bb7221df4/LICENSE`): Apache-2.0 with additional terms that take precedence;
commercial use without a separate license only below USD 2,000,000 of total funding and of annual revenue, and never
for a hosted API service that competes with SoMark's.
The upstream card is in `upstream/c708407f9d2b4df658f2543d9132b62bb7221df4/README.md`.
