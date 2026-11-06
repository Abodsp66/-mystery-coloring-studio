# Local PDF dependency

`jspdf.umd.min.js` is the unmodified official jsPDF **4.2.1** UMD distribution,
MIT licensed. See `jsPDF-LICENSE.txt` and `manifest.json` for the exact source,
verified npm SHA-512 integrity and local file SHA-256. Only the distribution and
license are vendored; the application has no npm installation/build step.

It is used for structured vector PDF export, not HTML rendering or importing
untrusted SVG/PDF files. No CDN is contacted for PDF generation.
