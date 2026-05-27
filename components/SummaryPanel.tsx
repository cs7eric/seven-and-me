function renderMarkdown(text: string): string {
  if (!text) return '';
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Code blocks
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
    `<pre style="background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:12px;margin:8px 0;overflow-x:auto;font-size:13px;line-height:1.6;"><code>${code.trim().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</code></pre>`
  );

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code style="background:#16181c;border:1px solid #30363d;border-radius:4px;padding:1px 6px;font-size:13px;font-family:monospace;">$1</code>');

  // Tables
  html = html.replace(/\n\|(.+)\|\n\|[\s\-:]+\|\n((?:\|.+\|\n?)*)/g, (_, header, body) => {
    const headerCells = header.split('|').map(c => c.trim()).filter(Boolean);
    const rows = body.trim().split('\n').map(row => row.split('|').map(c => c.trim()).filter(Boolean));
    let table = '<table style="border-collapse:collapse;width:100%;margin:8px 0;font-size:13px;">';
    table += '<thead><tr>';
    headerCells.forEach(cell => {
      table += `<th style="border:1px solid #30363d;padding:8px;text-align:left;background:#1c2732;color:#e7e9ea;">${cell}</th>`;
    });
    table += '</tr></thead><tbody>';
    rows.forEach(row => {
      table += '<tr>';
      row.forEach(cell => {
        table += `<td style="border:1px solid #30363d;padding:8px;">${cell}</td>`;
      });
      table += '</tr>';
    });
    table += '</tbody></table>';
    return table;
  });

  // Headers
  html = html.replace(/^### (.+)$/gm, '<h4 style="font-size:14px;font-weight:600;color:#1d9bf0;margin:12px 0 4px;">$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3 style="font-size:16px;font-weight:600;color:#1d9bf0;margin:14px 0 6px;border-bottom:1px solid #2f3336;padding-bottom:4px;">$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2 style="font-size:18px;font-weight:700;color:#1d9bf0;margin:16px 0 8px;">$1</h2>');

  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong style="color:#e7e9ea;font-weight:600;">$1</strong>');

  // Checklists
  html = html.replace(/^(\s*)- \[ \] (.+)$/gm, '<div style="display:flex;align-items:flex-start;gap:8px;margin:4px 0;"><span style="color:#71767b;">☐</span><span>$2</span></div>');
  html = html.replace(/^(\s*)- \[x\] (.+)$/gm, '<div style="display:flex;align-items:flex-start;gap:8px;margin:4px 0;"><span style="color:#1d9bf0;">☑</span><span>$2</span></div>');

  // Unordered lists
  html = html.replace(/^(\s*)-\s+(.+)$/gm, (m, indent, text) =>
    `<div style="padding-left:${indent.length + 16}px;margin:4px 0;">• ${text}</div>`
  );

  // Numbered lists
  html = html.replace(/^(\s*)(\d+)\.\s+(.+)$/gm, (m, indent, num, text) =>
    `<div style="padding-left:${indent.length + 16}px;margin:4px 0;">${num}. ${text}</div>`
  );

  // HR
  html = html.replace(/^---$/gm, '<hr style="border:none;border-top:1px solid #2f3336;margin:12px 0;">');

  // Paragraphs
  html = html.replace(/\n\n/g, '</p><p style="margin:8px 0;line-height:1.7;">');
  html = '<p style="margin:8px 0;line-height:1.7;">' + html + '</p>';
  html = html.replace(/<p style="margin:8px 0;line-height:1.7;"><\/p>/g, '');

  return html;
}

interface SummaryPanelProps {
  text: string;
}

export default function SummaryPanel({ text }: SummaryPanelProps) {
  return (
    <div style={{
      background: '#16181c',
      border: '1px solid #2f3336',
      borderRadius: '16px',
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '12px 16px',
        borderBottom: '1px solid #2f3336',
      }}>
        <div style={{ fontSize: '14px', fontWeight: '600', color: '#e7e9ea' }}>
          🧠 AI 摘要与总结
        </div>
      </div>
      <div
        style={{
          padding: '14px',
          minHeight: '200px',
          maxHeight: '400px',
          overflowY: 'auto',
          fontSize: '14px',
          lineHeight: '1.7',
          color: '#e7e9ea',
        }}
        dangerouslySetInnerHTML={{ __html: renderMarkdown(text) || '<span style="color:#71767b">摘要生成中...</span>' }}
      />
    </div>
  );
}