export type DiffLineType = 'add' | 'del' | 'context' | 'hunk' | 'meta';

export interface DiffLine {
  type: DiffLineType;
  text: string;
  oldLineNo: number | null;
  newLineNo: number | null;
}

export interface DiffFile {
  path: string;
  oldPath: string;
  newPath: string;
  status: 'added' | 'deleted' | 'renamed' | 'modified';
  additions: number;
  deletions: number;
  lines: DiffLine[];
  /** The file's own real raw diff text (its `diff --git` line onward), kept
   * verbatim for an exact copy action -- not reconstructed from `lines`. */
  raw: string;
}

const HUNK_HEADER = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

/** Parses a real unified `git diff` into per-file hunks with real line
 * counts and old/new line numbers -- nothing here is fabricated, it's a
 * straight read of the diff text the backend already produced. */
export function parseUnifiedDiff(diffText: string): DiffFile[] {
  if (!diffText.trim()) return [];

  const files: DiffFile[] = [];
  const rawLinesByFile: string[][] = [];
  let current: DiffFile | null = null;
  let currentRaw: string[] = [];
  let oldLineNo = 0;
  let newLineNo = 0;

  const pushCurrent = () => {
    if (current) {
      files.push(current);
      rawLinesByFile.push(currentRaw);
    }
  };

  for (const rawLine of diffText.split('\n')) {
    if (rawLine.startsWith('diff --git ')) {
      pushCurrent();
      const match = rawLine.match(/^diff --git a\/(.+) b\/(.+)$/);
      const oldPath = match?.[1] ?? '';
      const newPath = match?.[2] ?? oldPath;
      current = {
        path: newPath || oldPath,
        oldPath,
        newPath,
        status: 'modified',
        additions: 0,
        deletions: 0,
        lines: [],
        raw: ''
      };
      currentRaw = [rawLine];
      continue;
    }
    if (!current) continue;
    currentRaw.push(rawLine);

    if (rawLine.startsWith('new file mode')) {
      current.status = 'added';
      continue;
    }
    if (rawLine.startsWith('deleted file mode')) {
      current.status = 'deleted';
      continue;
    }
    if (rawLine.startsWith('rename from') || rawLine.startsWith('rename to')) {
      current.status = 'renamed';
      continue;
    }
    if (rawLine.startsWith('index ') || rawLine.startsWith('--- ') || rawLine.startsWith('+++ ')) {
      current.lines.push({ type: 'meta', text: rawLine, oldLineNo: null, newLineNo: null });
      continue;
    }

    const hunkMatch = rawLine.match(HUNK_HEADER);
    if (hunkMatch) {
      oldLineNo = parseInt(hunkMatch[1], 10);
      newLineNo = parseInt(hunkMatch[2], 10);
      current.lines.push({ type: 'hunk', text: rawLine, oldLineNo: null, newLineNo: null });
      continue;
    }

    if (rawLine.startsWith('+')) {
      current.additions++;
      current.lines.push({ type: 'add', text: rawLine.slice(1), oldLineNo: null, newLineNo: newLineNo++ });
    } else if (rawLine.startsWith('-')) {
      current.deletions++;
      current.lines.push({ type: 'del', text: rawLine.slice(1), oldLineNo: oldLineNo++, newLineNo: null });
    } else if (rawLine.startsWith(' ')) {
      current.lines.push({ type: 'context', text: rawLine.slice(1), oldLineNo: oldLineNo++, newLineNo: newLineNo++ });
    } else if (rawLine.startsWith('\\')) {
      // "\ No newline at end of file" -- not a real content line.
      continue;
    }
  }
  pushCurrent();
  files.forEach((f, i) => (f.raw = rawLinesByFile[i].join('\n')));
  return files;
}
