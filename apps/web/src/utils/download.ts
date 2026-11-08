export function csvContent(rows: (string | number)[][]) {
  return '\uFEFF' + rows.map(row => row.map(value => {
    let text = String(value);
    // 表格软件可能把用户文字当作公式执行。
    if (/^[\s]*[=+@-]/u.test(text) || /^[\t\r\n]/u.test(text)) text = "'" + text;
    return '"' + text.replaceAll('"', '""') + '"';
  }).join(',')).join('\r\n');
}
export function downloadText(name: string, content: string, type = 'text/plain;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement('a'); link.href = url; link.download = name;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
