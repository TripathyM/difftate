// A small line tokenizer: comments, strings, numbers, keywords, types, calls.
// Not a parser: good enough to read code, cheap enough to run on every visible row.

const KW = new Set(`
abstract and as assert async await break case catch class const continue def default defer del delete do elif else
enum export extends extern false final finally fn for from func function go if impl implements import in instanceof
interface is let loop match mod module mut namespace new nil none not null of or package pass private protected pub
public raise readonly return select self static struct super switch then this throw throws trait true try type
typeof undefined union unsafe use var void when where while with yield local end elseif fi done esac
`.split(/\s+/).filter(Boolean));

const HASH = new Set(["py", "sh", "zsh", "bash", "rb", "yaml", "yml", "toml", "r", "pl", "conf", "ini", "dockerfile", "mk", "makefile", "nix", "ex", "exs"]);
const DASH = new Set(["sql", "lua", "hs", "elm"]);
const NONE = new Set(["md", "markdown", "txt", "json", "csv", "lock", ""]);

export function langOf(path) {
  const base = path.split("/").pop().toLowerCase();
  if (base === "dockerfile" || base === "makefile") return base;
  const i = base.lastIndexOf(".");
  return i < 0 ? "" : base.slice(i + 1);
}

export function commentStyle(lang) {
  if (NONE.has(lang)) return { line: null, block: null };
  if (HASH.has(lang)) return { line: "#", block: null };
  if (DASH.has(lang)) return { line: "--", block: null };
  if (lang === "html" || lang === "xml" || lang === "svg" || lang === "vue") return { line: null, block: ["<!--", "-->"] };
  if (lang === "css" || lang === "scss") return { line: null, block: ["/*", "*/"] };
  return { line: "//", block: ["/*", "*/"] };
}

// Returns { spans: [{text, k}], inBlock } where k is a token kind for the theme.
export function tokenize(text, lang, inBlock = false) {
  const style = commentStyle(lang);
  const plain = NONE.has(lang);
  const spans = [];
  const push = (t, k) => {
    if (!t) return;
    const last = spans.at(-1);
    if (last && last.k === k) last.text += t;
    else spans.push({ text: t, k });
  };
  let i = 0;
  const n = text.length;
  if (plain) {
    // JSON gets strings and numbers; markdown headings stand out.
    if (lang === "md" || lang === "markdown") return { spans: [{ text, k: /^\s*#/.test(text) ? "keyword" : "text" }], inBlock };
    if (lang !== "json") return { spans: [{ text, k: "text" }], inBlock };
  }
  while (i < n) {
    if (inBlock && style.block) {
      const end = text.indexOf(style.block[1], i);
      if (end < 0) { push(text.slice(i), "comment"); return { spans, inBlock: true }; }
      push(text.slice(i, end + style.block[1].length), "comment");
      i = end + style.block[1].length;
      inBlock = false;
      continue;
    }
    const rest = text.slice(i);
    if (style.line && rest.startsWith(style.line) && !(style.line === "#" && lang === "sh" && text[i - 1] === "$")) {
      push(rest, "comment");
      break;
    }
    if (style.block && rest.startsWith(style.block[0])) { inBlock = true; continue; }
    const c = text[i];
    if (c === '"' || c === "'" || c === "`") {
      let j = i + 1;
      while (j < n && text[j] !== c) j += text[j] === "\\" ? 2 : 1;
      push(text.slice(i, j + 1), "string");
      i = j + 1;
      continue;
    }
    if (/[0-9]/.test(c) && !/[\w$]/.test(text[i - 1] ?? "")) {
      const m = /^(0x[0-9a-fA-F_]+|[0-9][0-9_]*(\.[0-9_]+)?([eE][+-]?\d+)?)/.exec(rest);
      push(m[0], "number");
      i += m[0].length;
      continue;
    }
    if (/[A-Za-z_$@]/.test(c)) {
      const m = /^[A-Za-z_$@][\w$]*/.exec(rest);
      const w = m[0];
      const after = text.slice(i + w.length).trimStart()[0];
      const k = KW.has(w) ? "keyword" : /^[A-Z][a-z0-9]/.test(w) && w.length > 1 ? "type" : after === "(" ? "function" : "text";
      push(w, k);
      i += w.length;
      continue;
    }
    const m = /^[^A-Za-z_$@0-9"'`\/#-]+|^./.exec(rest);
    push(m[0], /^[\s]+$/.test(m[0]) ? "text" : "punct");
    i += m[0].length;
  }
  return { spans, inBlock };
}
