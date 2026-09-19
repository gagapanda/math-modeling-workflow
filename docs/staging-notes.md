# Public Release Notes

This repository is the public, source-only distribution. It is not a mirror of the private competition workspace.

For every update:

- synchronize only reviewed general-purpose source files;
- retain public-specific privacy and missing-component adaptations;
- exclude private cases, evidence, course material, contest attachments, third-party templates and fonts, environments, caches and generated documents;
- refresh `docs/source-inventory.json` after the final edit;
- require the source inventory gate, Python/JSON structural checks and public regression suite to pass;
- stage the exact inventory path set and inspect the staged diff before committing.

The private controlled CUMCM LaTeX asset is intentionally absent because its downloaded class and fonts do not have a verified redistribution grant. Its absence is a public-edition boundary, not a successful template test.
