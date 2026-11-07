# Flow Symbols

Renamed alphanumeric subset of Liberation Sans Regular 2.1.5, from Debian's
`LiberationSans-Regular.ttf`. Space, digits and uppercase letters except I/O
are included. Original notices and SIL OFL 1.1 are in `LICENSE.txt`.

The browser measures the actual TTF with Canvas before enabling conversion.
SVG embeds it as a data URL; PDF embeds a subset of the same file. FontTools
ink bounds for native tests are in `metrics.json`. Re-run engine and browser
tests after changing the font. Do not substitute a system font silently.

Rebuild with fontTools Subsetter over the character set
` 0123456789ABCDEFGHJKLMNPQRSTUVWXYZ`; rename family/full-name records to
Flow Symbols and unique/PostScript records to FlowSymbols-Regular, preserving
all original legal metadata and the accompanying OFL license.
