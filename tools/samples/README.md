# Sample marketplace assets

This folder builds the fictional gallery files for the $49 one-off trial: one job's quote and estimate files turned into a packet and a follow-up list, plus an optional photo closeout exception report.

The pictures are samples. They use the fictional contractor North Pine Demo Builders and fictional job NP-1042. They are marked SAMPLE and Fictional data. They do not show a studio brand, a contact method, a rating, or a third-party logo.

## Regenerate

From the repository root, with the project virtualenv:

```sh
.venv/bin/python tools/samples/generate_samples.py
```

Pillow, reportlab, and pypdf are already pinned in `requirements.txt`. The script writes `assets/samples/` and then checks size, page count, the sample money figures, and a block list (brand names, contact details, street-address words, certification and revenue claims). It also records every drawn string against the box it belongs in — the cover, a card, a table cell, or a page region — and exits non-zero if any glyph runs past that box. A tiny self-check confirms the detector flags an overflowing string and accepts one that fits.

The script is not part of the CI test set. Do not add it under `tests/` unless the trusted manifest is updated in the same change.

## Fonts

`fonts/` contains unmodified Liberation Sans and Liberation Mono (regular and bold sans, regular mono). They are under the SIL Open Font License 1.1. The license and copyright notice are in `fonts/OFL.txt`. Reserved font names are unchanged because the files are unmodified.

## Files written

| File | Size |
|---|---|
| `cf-r3_fiverr-cover-packet_1280x769_v1.png` | 1280×769 PNG, 72 DPI |
| `cf-r3_fiverr-cover-followup_1280x769_v1.png` | 1280×769 PNG, 72 DPI |
| `cf-r3_fiverr-cover-photo_1280x769_v1.png` | 1280×769 PNG, 72 DPI |
| `cf-r3_upwork-catalog-packet_1000x750_v1.png` | 1000×750 PNG, 72 DPI |
| `cf-r3_upwork-catalog-followup_1000x750_v1.png` | 1000×750 PNG, 72 DPI |
| `cf-r3_upwork-catalog-photo_1000x750_v1.png` | 1000×750 PNG, 72 DPI |
| `cf-r3_upwork-catalog-process_1000x750_v1.png` | 1000×750 PNG, 72 DPI |
| `cf-r3_sample-quote-packet_FICTIONAL_v1.pdf` | 3-page letter PDF |
| `cf-r3_sample-photo-exception_FICTIONAL_v1.pdf` | 3-page letter PDF |

Cover headlines stay short: Quote Packet, Follow-Up List, Exception Report, and Receive, Organize, Return. The rows inside the close-ups are fictional sample data, not a second headline.

The quote packet copies two stated figures (4,800.00 and 640.00) and leaves unstated lines blank. Their sum, 5,440.00, is labeled as a subtotal of stated lines, not a job total. The photo report uses flat color blocks and filenames. A flag means a file is missing or unclear. It is not a judgment of the work and not a payment decision.
