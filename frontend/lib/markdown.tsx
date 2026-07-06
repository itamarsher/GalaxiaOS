// Tiny, dependency-free Markdown renderer.
//
// Decisions, plans and the agent chat are authored in Markdown by the LLM; we
// render a safe subset here rather than pulling in a heavy library. Input is
// HTML-escaped first, then a small set of block/inline rules run over it, so the
// only tags that ever reach the DOM are the ones we emit.

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Only allow safe URL schemes in links (no javascript:, data:, etc.).
function safeUrl(url: string): string {
  const u = url.trim();
  if (/^(https?:\/\/|mailto:|\/|#)/i.test(u)) return u;
  return "#";
}

function inline(text: string): string {
  let s = escapeHtml(text);
  // Inline code first so its contents aren't touched by other rules.
  s = s.replace(/`([^`]+)`/g, (_m, c) => `<code>${c}</code>`);
  // Links [text](url)
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, t, u) =>
    `<a href="${safeUrl(u)}" target="_blank" rel="noopener noreferrer">${t}</a>`);
  // Bold then italic.
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
  s = s.replace(/_([^_]+)_/g, "<em>$1</em>");
  return s;
}

/** Render a Markdown string to a safe HTML string. */
export function renderMarkdown(src: string): string {
  const lines = (src ?? "").replace(/\r\n/g, "\n").split("\n");
  const html: string[] = [];
  let i = 0;
  let listType: "ul" | "ol" | null = null;

  const closeList = () => {
    if (listType) { html.push(`</${listType}>`); listType = null; }
  };

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block.
    if (/^```/.test(line.trim())) {
      closeList();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i].trim())) { buf.push(lines[i]); i++; }
      i++; // skip closing fence
      html.push(`<pre><code>${escapeHtml(buf.join("\n"))}</code></pre>`);
      continue;
    }

    // Blank line — paragraph/list break.
    if (line.trim() === "") { closeList(); i++; continue; }

    // Headings.
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      closeList();
      const level = Math.min(6, Math.max(3, h[1].length + 2)); // keep headings compact
      html.push(`<h${level}>${inline(h[2])}</h${level}>`);
      i++; continue;
    }

    // Blockquote.
    if (/^>\s?/.test(line)) {
      closeList();
      html.push(`<blockquote>${inline(line.replace(/^>\s?/, ""))}</blockquote>`);
      i++; continue;
    }

    // Unordered list item.
    const ul = /^\s*[-*]\s+(.*)$/.exec(line);
    if (ul) {
      if (listType !== "ul") { closeList(); html.push("<ul>"); listType = "ul"; }
      html.push(`<li>${inline(ul[1])}</li>`);
      i++; continue;
    }

    // Ordered list item.
    const ol = /^\s*\d+\.\s+(.*)$/.exec(line);
    if (ol) {
      if (listType !== "ol") { closeList(); html.push("<ol>"); listType = "ol"; }
      html.push(`<li>${inline(ol[1])}</li>`);
      i++; continue;
    }

    // Paragraph: gather consecutive non-blank, non-special lines.
    closeList();
    const para: string[] = [line];
    i++;
    while (
      i < lines.length && lines[i].trim() !== "" &&
      !/^```/.test(lines[i].trim()) && !/^(#{1,6})\s/.test(lines[i]) &&
      !/^>\s?/.test(lines[i]) && !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i])
    ) { para.push(lines[i]); i++; }
    html.push(`<p>${para.map(inline).join("<br/>")}</p>`);
  }
  closeList();
  return html.join("");
}

/** Render Markdown as a styled block. */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div
      className={`md${className ? ` ${className}` : ""}`}
      dangerouslySetInnerHTML={{ __html: renderMarkdown(children) }}
    />
  );
}
