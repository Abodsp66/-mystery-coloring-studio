'use strict';
// Shared, tested helpers for the portable numeric font and physical export QA.
window.Studio = (() => {
  let fontURL = '';
  const fontReady = (async () => {
    const response = await fetch('fonts/StudioDigits.ttf');
    if (!response.ok) throw new Error('تعذر تحميل خط الرموز المحلي.');
    const bytes = await response.arrayBuffer();
    const face = await new FontFace('Studio Digits', bytes).load();
    document.fonts.add(face);
    fontURL = 'data:font/ttf;base64,' + btoa(String.fromCharCode(...new Uint8Array(bytes)));
    await document.fonts.load('1000px "Studio Digits"', '0123456789');
  })();
  function fontStyle() {
    return `<defs><style>@font-face{font-family:'Studio Digits';src:url(${fontURL}) format('truetype');font-weight:normal;font-style:normal}text{font-family:'Studio Digits',sans-serif}</style></defs>`;
  }
  function parsePalette(value) {
    if (!value || !Array.isArray(value.colors) || value.colors.length < 1 || value.colors.length > 48)
      throw new Error('يجب أن تحتوي لوحة الأقلام على 1–48 لونًا.');
    const colors = value.colors.map(item => {
      const hex = typeof item === 'string' ? item : item?.hex;
      if (typeof hex !== 'string' || !/^#[0-9a-f]{6}$/i.test(hex)) throw new Error('استخدم ألوان HEX بصيغة #RRGGBB.');
      return [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
    });
    if (new Set(colors.map(c => c.join(','))).size !== colors.length) throw new Error('توجد ألوان مكررة في اللوحة.');
    return {name: String(value.name || 'لوحة الأقلام').slice(0, 60), colors,
      names: value.colors.map((item, i) => String(typeof item === 'object' && item.name || i + 1).slice(0, 60))};
  }
  function exportCheck(result, stroke) {
    const qa = result.metrics.printQA;
    const strokeSafe = stroke <= qa.maximumSafeStrokeMM + 1e-5;
    const ready = result.metrics.missing === 0 && qa.labelConflictIds.length === 0 && strokeSafe;
    return {status: ready ? 'passed' : 'review', ready, strokeSafe, lineWidthMM: stroke,
      minimumGapMM: qa.minimumInkClearanceMM - stroke / 2 - qa.exportAllowanceMM,
      unresolvedCells: result.metrics.missing, labelConflictIds: qa.labelConflictIds,
      scope: 'Physical geometry only; inspect source fidelity, mystery and actual paper printing.'};
  }
  return {fontReady, fontStyle, parsePalette, exportCheck, fontBase64: () => fontURL.split(',')[1]};
})();
