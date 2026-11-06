'use strict';
// Local jsPDF 4.2.1, MIT. Reuse the engine's paths and measured label origins;
// no screenshot/raster conversion and no network request during PDF export.
window.StudioPDF = {
  async create(r, mode, stroke, tone, check) {
    await Studio.fontReady;
    const [pw, ph] = r.settings.paper;
    const doc = new jspdf.jsPDF({orientation: pw > ph ? 'landscape' : 'portrait',
      unit: 'mm', format: [pw, ph], precision: 6, putOnlyUsedFonts: true, compress: true});
    doc.addFileToVFS('StudioDigits.ttf', Studio.fontBase64());
    doc.addFont('StudioDigits.ttf', 'StudioDigits', 'normal');
    doc.setFont('StudioDigits', 'normal');
    doc.setProperties({title: 'Mystery Coloring Studio V6', subject: check.ready ? 'Geometry checked' : 'Draft - review required'});
    const ox = (pw - r.w * r.mm) / 2;
    function path(data) {
      const tokens = data.match(/[MLCZ]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?/g) || [];
      const operations = [];
      for (let i = 0; i < tokens.length;) {
        const op = tokens[i++], count = {M: 2, L: 2, C: 6, Z: 0}[op];
        if (count === undefined) throw new Error('مسار PDF غير صالح.');
        const coords = tokens.slice(i, i + count).map(Number); i += count;
        if (coords.length !== count || !coords.every(Number.isFinite)) throw new Error('إحداثيات PDF غير صالحة.');
        operations.push({op: {M: 'm', L: 'l', C: 'c', Z: 'h'}[op],
          c: coords.map((v, j) => j % 2 ? 12 + v * r.mm : ox + v * r.mm)});
      }
      doc.path(operations);
    }
    doc.setLineJoin('round'); doc.setLineCap('round');
    if (mode === 'solution') {
      r.solutionPaths.forEach((data, i) => {
        if (!data) return;
        doc.setFillColor(...r.palette[i]); path(data); doc.fillEvenOdd();
      });
    } else {
      doc.setDrawColor(tone); doc.setLineWidth(stroke); path(r.network); doc.stroke();
      for (const c of r.cells) {
        const p = c.label;
        if (!p) {
          if (mode === 'audit') {
            doc.setFillColor('#ffeeec'); path(c.path); doc.fillEvenOdd();
            doc.setDrawColor('#d34f45'); doc.setLineWidth(.18); path(c.path); doc.stroke();
          }
          continue;
        }
        const glyph = r.glyphs[String(c.color + 1)], em = p.pt * 25.4 / 72;
        const angle = p.angle * Math.PI / 180;
        const x = ox + p.x * r.mm - em * glyph.cx * Math.cos(angle) + em * glyph.cy * Math.sin(angle);
        const y = 12 + p.y * r.mm - em * glyph.cx * Math.sin(angle) - em * glyph.cy * Math.cos(angle);
        doc.setFont('StudioDigits', 'normal'); doc.setFontSize(p.pt); doc.setTextColor('#4e5752');
        doc.text(String(c.color + 1), x, y, {angle: -p.angle, baseline: 'alphabetic'});
      }
    }
    const rowSize = 24, rows = Math.ceil(r.palette.length / rowSize);
    const sw = Math.min(10, (pw - 24) / Math.min(rowSize, r.palette.length));
    const start = (pw - sw * Math.min(rowSize, r.palette.length)) / 2;
    r.palette.forEach((color, i) => {
      const x = start + (i % rowSize) * sw, y = ph - (rows > 1 ? 38 : 28) + Math.floor(i / rowSize) * 10;
      doc.setFillColor(...color); doc.setDrawColor('#bbbbbb'); doc.setLineWidth(.1);
      doc.rect(x + 1, y, sw - 2, 5, 'FD');
      doc.setFont('StudioDigits', 'normal'); doc.setFontSize(2.7 * 72 / 25.4); doc.setTextColor('#333333');
      doc.text(String(i + 1), x + sw / 2, y + 9, {align: 'center'});
    });
    doc.setFont('helvetica', 'normal'); doc.setFontSize(2 * 72 / 25.4); doc.setTextColor('#555555');
    doc.text(`V6 | ${check.ready ? 'GEOMETRY CHECKED' : 'DRAFT - REVIEW'} | ${r.metrics.cells} cells | ${r.metrics.missing} unnumbered | Print 100%`, pw / 2, ph - 12, {align: 'center'});
    return doc.output('blob');
  }
};
