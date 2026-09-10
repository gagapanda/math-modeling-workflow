# Visual Review Context Safety

Visual review must preserve enough context for reasoning, tool output, and finalization. A rendered page can be valid on disk yet still be expensive when attached to a long conversation. Treat image loading as a bounded resource.

## Required Review Sequence

1. Finish the last layout-sensitive build before starting visual review.
2. Keep original rendered pages on disk for hashes and targeted follow-up inspection. Generate bounded JPEG previews with `scripts/prepare_visual_previews.py`, normally at 700-900 px wide.
3. Inspect at most two page images in one request/batch. After each batch, write a compact finding covering page numbers and clipping, overlap, glyph, and layout status.
4. Use an original-resolution crop only for a suspected defect or a detail unreadable in the preview.
5. If the conversation already contains substantial logs, source text, or earlier images, move visual review to a fresh task/context. Carry forward only the case path, page count, hashes, and compact findings.
6. Before finalization, verify that the recorded page list and hashes cover every final page.

Do not retry a context-window failure by attaching the same images again. Reduce preview dimensions, split the batch, or continue in a fresh context. A contact sheet can help navigation, but it does not replace readable inspection of each page.
