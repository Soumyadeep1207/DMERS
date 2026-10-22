/** Report exports: CSV and a black-and-white printable PDF (no colour fills anywhere). */

export function safeCell(value) {
  const text = value === null || value === undefined ? '' : String(value);
  return /^[=+\-@]/.test(text) ? `'${text}` : text;
}

export function toCsv(result) {
  const quote = cell => `"${String(cell).replaceAll('"', '""')}"`;
  const parameters = Object.entries(result.parameters || {}).map(([k, v]) => `${k}=${v}`).join(', ') || 'none';
  const rows = [[result.title], ['Requirement', result.requirement, 'Review II query', result.review2_query], ['Parameters', parameters], [], result.columns,
    ...result.rows.map(row => row.map(safeCell))];
  return `﻿${rows.map(row => row.map(quote).join(',')).join('\r\n')}`;
}

/** Column widths (in characters) proportional to content, never below the header, capped so a page stays readable. */
export function columnWidths(columns, rows, totalChars = 100) {
  const natural = columns.map((name, i) => Math.min(40, Math.max(String(name).length, ...rows.map(r => String(r[i] ?? '').length), 3)));
  const sum = natural.reduce((a, b) => a + b, 0);
  return natural.map(w => Math.max(4, Math.floor((w / sum) * totalChars)));
}

export const clip = (text, width) => {
  const s = String(text ?? '');
  return s.length > width ? `${s.slice(0, Math.max(1, width - 1))}…` : s;
};

/** Pages of plain text rows: a header block on page 1, the table header repeated on every page. */
export function layoutReport(result, { rowsFirstPage = 28, rowsPerPage = 40, generatedAt = new Date() } = {}) {
  const widths = columnWidths(result.columns, result.rows);
  const header = result.columns.map((c, i) => clip(c, widths[i]));
  const body = result.rows.map(row => row.map((cell, i) => clip(cell, widths[i])));
  const pages = [];
  let index = 0;
  while (index < body.length || pages.length === 0) {
    const capacity = pages.length === 0 ? rowsFirstPage : rowsPerPage;
    pages.push({ rows: body.slice(index, index + capacity) });
    index += capacity;
  }
  const meta = [
    result.title,
    `Requirement ${result.requirement} · Review II query ${result.review2_query} · ${result.sql_feature}`,
    `Generated ${generatedAt.toLocaleString()} (data in ${result.time_zone || 'database time zone'})`,
    `Parameters: ${Object.entries(result.parameters || {}).map(([k, v]) => `${k}=${v}`).join(', ') || 'none'}`,
  ];
  return { meta, header, widths, pages, rowCount: result.rows.length };
}

/** Draws the layout with jsPDF using black text and thin black rules only. */
export async function downloadPdf(result) {
  const { jsPDF } = await import('jspdf');
  const layout = layoutReport(result);
  const pdf = new jsPDF({ unit: 'pt', format: 'a4', orientation: layout.header.length > 6 ? 'landscape' : 'portrait' });
  const width = pdf.internal.pageSize.getWidth(), margin = 36, usable = width - margin * 2;
  const totalChars = layout.widths.reduce((a, b) => a + b, 0);
  const starts = layout.widths.reduce((acc, w) => [...acc, acc.at(-1) + (w / totalChars) * usable], [margin]);
  pdf.setTextColor(0, 0, 0); pdf.setDrawColor(0, 0, 0);
  const drawHeader = y => {
    pdf.setFont('helvetica', 'bold'); pdf.setFontSize(9);
    layout.header.forEach((text, i) => pdf.text(text, starts[i], y));
    pdf.setLineWidth(0.8); pdf.line(margin, y + 4, margin + usable, y + 4);
    pdf.setFont('helvetica', 'normal');
    return y + 18;
  };
  layout.pages.forEach((page, pageIndex) => {
    if (pageIndex > 0) pdf.addPage();
    let y = margin + 8;
    if (pageIndex === 0) {
      pdf.setFont('helvetica', 'bold'); pdf.setFontSize(15); pdf.text(layout.meta[0], margin, y); y += 20;
      pdf.setFont('helvetica', 'normal'); pdf.setFontSize(9);
      layout.meta.slice(1).forEach(line => { pdf.text(line, margin, y); y += 13; });
      y += 8;
    }
    y = drawHeader(y);
    pdf.setFontSize(9);
    page.rows.forEach(row => {
      row.forEach((cell, i) => pdf.text(cell, starts[i], y));
      pdf.setLineWidth(0.2); pdf.line(margin, y + 4, margin + usable, y + 4);
      y += 15;
    });
    if (!page.rows.length) pdf.text('No rows.', margin, y);
    pdf.setFontSize(8); pdf.text(`Page ${pageIndex + 1} of ${layout.pages.length} · ${layout.rowCount} row(s) · DMERS`, margin, pdf.internal.pageSize.getHeight() - 20);
  });
  pdf.save(`dmers-${result.key}.pdf`);
}
