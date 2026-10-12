# DocScout - identity usage

> Citation-grounded regulatory retrieval over RBI/SEBI circulars. Every answer cites its source or refuses to answer.
> Audience: Analysts, auditors and fintech compliance teams

## Concept
A bookmark ribbon (the document under review) pierced by a compass-needle negative space - the scout that always points at the cited source.

The compact mark carries the identity alone; the primary lockup pairs it with the
'DocScout' wordmark (Space Grotesk SemiBold, converted to outlines - no font
required to render the production files).

## Colour
| Role | Light backgrounds | Dark backgrounds |
|---|---|---|
| Structure / ink | `#0B1220` | `#F8FAFC` |
| Accent | `#B45309` | `#F59E0B` |

Single-colour reproduction: use `*-mono.svg` (all geometry set to
`currentColor`); set any colour ≥ 4.5:1 contrast against the background.
Negative space (needle, slashes, core, route) must always show the background -
never fill it with a second colour.

## Typography
Wordmark: **Space Grotesk SemiBold (600)**, SIL Open Font License 1.1
(see `../FONT-LICENSE.txt`). In delivered SVGs the letterforms are outlined
vector paths, so no font installation is ever required. Do not re-typeset the
name in another face or alter casing/spelling ('DocScout').

## Size & clear space
- Compact mark: minimum **16 px**; verified legible at 16/32/64 px.
- Primary lockup: minimum **24 px** height (≈ 9 mm print).
- Clear space: **¼ of the mark height** on all sides of any lockup or mark.
- App icon / avatar: use `docscout-appicon.svg` (tile `#0B1220`, radius 56/256).

## Misuse
Do not rotate, skew, add gradients/shadows/outlines, recolor outside the
palette, place the light variant on mid-tone backgrounds, or reconstruct the
mark from live text.

## Files
- `svg/docscout-primary.svg` · `-primary-dark.svg` · `-primary-mono.svg`
- `svg/docscout-mark.svg` · `-mark-dark.svg` · `-mark-mono.svg` · `-appicon.svg`
- `png/docscout-mark-1024|512|256|64|32|16.png`, `docscout-mark-dark-1024.png`,
  `docscout-primary-light-1600.png`, `docscout-primary-dark-1600.png`,
  `docscout-appicon-512.png`
