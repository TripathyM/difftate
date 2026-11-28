// Which words of a changed line differ from its pair's, for layout D's word highlight. DOM-free.

// Words, runs of blanks, and every other character alone
const tokens = (text) => text.match(/[\p{L}\p{N}_]+|\s+|[^\p{L}\p{N}_\s]/gu) ?? [];

// More pairs of tokens than this aren't compared: such a line is generated, not edited
const MOST = 1_000_000;

// Which tokens of <a> and of <b> are in a longest sequence that both have
function kept(a, b) {
  const keptA = a.map(() => false);
  const keptB = b.map(() => false);
  // longest[i][j]: how long that sequence is for what is left from a[i] and b[j]
  const longest = Array.from({ length: a.length + 1 }, () => new Uint32Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      longest[i][j] = a[i] === b[j] ? longest[i + 1][j + 1] + 1 : Math.max(longest[i + 1][j], longest[i][j + 1]);
    }
  }
  for (let i = 0, j = 0; i < a.length && j < b.length;) {
    if (a[i] === b[j]) { keptA[i++] = true; keptB[j++] = true; }
    else if (longest[i + 1][j] >= longest[i][j + 1]) i++;
    else j++;
  }
  return [keptA, keptB];
}

// The [start, end) of what of <text>, as <all> its tokens, isn't <same>. Blanks alone don't part
// two changes
function ranges(text, all, same) {
  const found = [];
  let at = 0;
  all.forEach((token, i) => {
    const end = at + token.length;
    if (!same[i]) {
      const last = found.at(-1);
      if (last && !text.slice(last[1], at).trim()) last[1] = end;
      else found.push([at, end]);
    }
    at = end;
  });
  return found;
}

const inked = (parts) => parts.reduce((n, part) => n + part.replace(/\s/g, "").length, 0);

/** What changed from the line <before> to the line <after>: [ranges of before, ranges of after],
 *  each [start, end) in the line's text. null when they have too little in common to be one line
 *  edited (under a third of the shorter one, blanks aside), or are too long to compare. */
export function changedWords(before, after) {
  const [a, b] = [tokens(before), tokens(after)];
  if (a.length * b.length > MOST) return null;
  const [keptA, keptB] = kept(a, b);
  const common = inked(a.filter((_, i) => keptA[i]));
  if (!common || common * 3 < Math.min(inked(a), inked(b))) return null;
  return [ranges(before, a, keptA), ranges(after, b, keptB)];
}
