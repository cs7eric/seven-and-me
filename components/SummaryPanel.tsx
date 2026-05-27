function renderMarkdown(text: string): string {
  if (!text) return '';
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Code blocks (```...```)
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_: string, _lang: string, code: string) =>
    `<pre style="background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:12px;margin:8px 0;overflow-x:auto;font-size:13px;line-height:1.6;"><code>${code.trim().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</code></pre>`
  );

  // Inline code (`...`)
  html = html.replace(/`([^`]+)`/g, '<code style="background:#16181c;border:1px solid #30363d;border-radius:4px;padding:1px 6px;font-size:13px;font-family:monospace;">$1</code>');

  // Tables (处理 Markdown 表格)
  html = html.replace(/\n\|(.+)\|\n\|[\s\-:]+\|\n((?:\|.+\|\n?)*)/g, (_: string, header: string, body: string) => {
    const headerCells = header.split('|').map((c: string) => c.trim()).filter(Boolean);
    const rows = body.trim().split('\n').map((row: string) => row.split('|').map((c: string) => c.trim()).filter(Boolean));
    let table = '<table style="border-collapse:collapse;width:100%;margin:8px 0;font-size:13px;border:1px solid #2f3336;border-radius:8px;overflow:hidden;">';
    table += '<thead><tr>';
    headerCells.forEach((cell: string) => {
      table += `<th style="border:1px solid #2f3336;padding:10px 12px;text-align:left;background:#1c2732;color:#e7e9ea;font-weight:600;font-size:13px;">${cell}</th>`;
    });
    table += '</tr></thead><tbody>';
    rows.forEach((row: string[]) => {
      table += '<tr>';
      row.forEach((cell: string) => {
        table += `<td style="border:1px solid #2f3336;padding:10px 12px;font-size:13px;color:#e7e9ea;">${cell}</td>`;
      });
      table += '</tr>';
    });
    table += '</tbody></table>';
    return table;
  });

  // Headers (h2, h3, h4)
  html = html.replace(/^#### (.+)$/gm, '<h4 style="font-size:13px;font-weight:600;color:#71767b;margin:10px 0 4px;">$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h4 style="font-size:15px;font-weight:600;color:#1d9bf0;margin:14px 0 6px;">$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3 style="font-size:17px;font-weight:700;color:#1d9bf0;margin:16px 0 8px;padding-bottom:6px;border-bottom:1px solid #2f3336;">$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2 style="font-size:20px;font-weight:700;color:#1d9bf0;margin:18px 0 10px;">$1</h2>');

  // Bold (**text**)
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong style="color:#e7e9ea;font-weight:600;background:#1c2732;padding:0 4px;border-radius:3px;">$1</strong>');

  // Checklists (- [ ] / - [x])
  html = html.replace(/^(\s*)- \[ \] (.+)$/gm, '<div style="display:flex;align-items:flex-start;gap:10px;margin:5px 0;padding-left:4px;"><span style="color:#536471;font-size:15px;line-height:1.6;">☐</span><span style="color:#e7e9ea;font-size:14px;line-height:1.6;">$2</span></div>');
  html = html.replace(/^(\s*)- \[x\] (.+)$/gm, '<div style="display:flex;align-items:flex-start;gap:10px;margin:5px 0;padding-left:4px;"><span style="color:#1d9bf0;font-size:15px;line-height:1.6;">☑</span><span style="color:#e7e9ea;font-size:14px;line-height:1.6;">$2</span></div>');

  // Unordered lists (- item)
  html = html.replace(/^(\s*)-\s+(.+)$/gm, (m: string, indent: string, text: string) =>
    `<div style="padding-left:${indent.length + 20}px;margin:4px 0;font-size:14px;line-height:1.7;"><span style="color:#1d9bf0;margin-right:8px;">•</span>${text}</div>`
  );

  // Numbered lists (1. item)
  html = html.replace(/^(\s*)(\d+)\.\s+(.+)$/gm, (m: string, indent: string, num: string, text: string) =>
    `<div style="padding-left:${indent.length + 20}px;margin:4px 0;font-size:14px;line-height:1.7;"><span style="color:#1d9bf0;font-weight:600;margin-right:8px;">${num}.</span>${text}</div>`
  );

  // Horizontal rules (---)
  html = html.replace(/^---$/gm, '<hr style="border:none;border-top:1px solid #2f3336;margin:16px 0;">');

  // Line breaks -> paragraphs（处理段落换行）
  html = html.replace(/\n\n+/g, '</p><p style="margin:8px 0;line-height:1.8;color:#e7e9ea;">');
  html = '<p style="margin:8px 0;line-height:1.8;color:#e7e9ea;">' + html + '</p>';
  html = html.replace(/<p style="margin:8px 0;line-height:1.8;color:#e7e9ea;"><\/p>/g, '');
  html = html.replace(/<p style="margin:8px 0;line-height:1.8;color:#e7e9ea;">([\s\S]*?)<\/p>/g, (match: string, content: string) => {
    // Clean up empty paragraphs
    if (content.trim() === '') return '';
    return match;
  });

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