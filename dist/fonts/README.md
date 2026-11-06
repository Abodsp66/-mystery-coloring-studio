# Studio Digits

`StudioDigits.ttf` is a renamed subset of Liberation Sans Regular 2.1.5
(`LiberationSans-Regular.ttf` from Debian's `fonts-liberation`). It contains
space and the ten decimal digits. The original copyright and SIL OFL 1.1
are preserved in `LICENSE.txt`; reserved family names were replaced with
Studio Digits / StudioDigits-Regular in the modified font's naming records.

The browser measures this exact font with Canvas before starting conversion.
SVG embeds the TTF as a data URL, and jsPDF embeds/subsets the same font in PDF.
Numeric labels must not silently fall back to a system font: that would
invalidate the measured ink bounds. UI and explanatory text use system fonts.

To rebuild with fontTools 4.61.1, subset the source to Unicode U+0020 and
U+0030–0039 with `fontTools.subset.Subsetter`, then set name IDs 1/16 to
`Studio Digits`, IDs 2/17 to `Regular`, and IDs 3/4/6 to
`StudioDigits-Regular` before saving. Keep the OFL license with the result.
Re-run native and browser checks after any font change; geometry depends on it.
