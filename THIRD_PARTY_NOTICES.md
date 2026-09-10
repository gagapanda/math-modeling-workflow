# Third-party sources and dependency notices

This is a source-only **release candidate**. Project material is offered under the root MIT LICENSE following the project initiator's authorization. That grant does not relicense third-party dependencies, establish independent ownership of every line, or approve an actual remote upload. Successful tests do not establish ownership.

Machine-readable versioned evidence: [dependency-licenses.json](docs/dependency-licenses.json). Source-file declarations: [source-inventory.json](docs/source-inventory.json). The private C2 audit retains fetched upstream snapshots and wheel license-file hashes; those private artifacts are not bundled here. URLs and hashes identify the consulted evidence, not a promise of perpetual availability.

## Export dependencies tested in isolated Python

| Component | Version | Upstream declaration |
|---|---|---|
| python-docx | 1.2.0 | MIT |
| pypdf | 6.10.0 | BSD-3-Clause |
| Pillow | 12.3.0 | MIT-CMU |
| lxml | 6.1.1 | BSD-3-Clause principal license, plus LICENSES.txt exceptions/components |
| typing_extensions | 4.16.0 | PSF-2.0 |

The exact CPython 3.12 Windows x86_64 wheels were hash-checked against official PyPI metadata, then installed offline into an isolated environment. This does not certify vulnerabilities or all embedded native components. In particular, lxml's LICENSES.txt describes separately licensed ElementTree origins, test scripts and resources; its top-level metadata is not a blanket clearance.

## Optional modeling dependencies (metadata review only)

NumPy, pandas, SciPy, Matplotlib, scikit-learn, statsmodels, openpyxl and pymoo are listed with consulted versions and exact metadata scope in the JSON inventory. They were **not installed or model-tested in the new export environment**. Matplotlib's specific agreement must not be reduced to an unqualified generic PSF license; unresolved BSD variants remain explicitly unresolved. Transitive and compiled-library notices need a separate audit before binary distribution.

## External prerequisites — not bundled

- Pandoc: the consulted version's COPYRIGHT states GPL version 2 or later with exceptions and other component notices. See the source URL and snapshot hash in the inventory.
- LibreOffice: the official license page describes MPL 2.0 and other incorporated/historical licensing; the installed distribution's LICENSE remains necessary for bundling review.
- Poppler: the homepage was reachable, but the exact installed distribution license was **not independently verified** in this batch. No Poppler binaries are distributed.
- Python: version-specific PSF agreement and incorporated-software notices apply to the interpreter; the interpreter is not distributed.
- Fonts: only font names appear in configuration. System font availability, substitution, embedding and redistribution rights require separate review. No fonts are copied.

## Excluded legacy exporter

The prior external exporter was traced to an upstream repository, but its redistribution permission remains unconfirmed. A request for one default-branch LICENSE path returned 404; this is **not proof that all branches or permissions are absent**. Its source is excluded. The public backend is newly written orchestration; this description is not a legal clean-room claim or an authorship certification.

No third-party wheels, executables, font files, downloaded papers, course code, contest data or legacy exporter sources are shipped in this candidate. These summaries do not replace upstream license texts. If distribution changes to bundle any of them, reopen the license and notice review before release.
