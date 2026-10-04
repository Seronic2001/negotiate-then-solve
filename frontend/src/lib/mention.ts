/** Put a picked class, course or name into the text being written: at the cursor, with spaces
 * around it, and only once. Returns null when the text already mentions it. */
export function insertMention(text: string, phrase: string, at: number = text.length): { text: string; cursor: number } | null {
  if (mentions(text, phrase)) return null;
  if (!text.trim()) {
    const t = phrase.charAt(0).toUpperCase() + phrase.slice(1);
    return { text: t, cursor: t.length };
  }
  const before = text.slice(0, at);
  const after = text.slice(at);
  const head = before + (before && !/\s$/.test(before) ? " " : "") + phrase;
  const tail = (after && !/^[\s.,;:!?]/.test(after) ? " " : "") + after;
  return { text: head + tail, cursor: head.length };
}

export const mentions = (text: string, phrase: string) => text.toLowerCase().includes(phrase.toLowerCase());

/** Apply a mention to a textarea's value and put the cursor right after it. */
export function mentionInto(el: HTMLTextAreaElement | null, text: string, phrase: string, set: (t: string) => void): void {
  const got = insertMention(text, phrase, el && document.activeElement === el ? el.selectionStart : (el?.selectionStart ?? text.length));
  if (!got) return;
  set(got.text);
  requestAnimationFrame(() => {
    el?.focus();
    el?.setSelectionRange(got.cursor, got.cursor);
  });
}

/** Take a mentioned phrase back out, tidying the spaces it leaves. */
export function removeMention(text: string, phrase: string): string {
  const i = text.toLowerCase().indexOf(phrase.toLowerCase());
  if (i < 0) return text;
  const out = (text.slice(0, i).trimEnd() + " " + text.slice(i + phrase.length).trimStart()).replace(/\s+([.,;:!?])/g, "$1").trim();
  return out ? out.charAt(0).toUpperCase() + out.slice(1) : out;
}
