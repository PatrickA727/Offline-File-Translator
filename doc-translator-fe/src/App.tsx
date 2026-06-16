import { useState, useRef } from "react";
import toast from "react-hot-toast";

const BE_URL = import.meta.env.VITE_BACKEND_URL;

const LANGS = ["zh", "ja", "en", "id"] as const;
type Lang = (typeof LANGS)[number];
const LANG_LABELS: Record<Lang, string> = {
  zh: "Chinese",
  ja: "Japanese",
  en: "English",
  id: "Indonesian",
};

const MAX_VISIBLE = 3;

function downloadBlob(blob: Blob, filename: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

function parseFilename(res: Response, fallback: string): string {
  const disposition = res.headers.get("Content-Disposition") || "";
  if (disposition.includes("filename*="))
    return decodeURIComponent(disposition.split("filename*=utf-8''")[1]);
  return disposition.split("filename=")[1]?.replaceAll('"', '') || fallback;
}

function poll(url: string, interval: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const id = setInterval(async () => {
      try {
        const res = await fetch(url);
        if (!res.ok) { clearInterval(id); reject(new Error("Polling failed")); return; }
        const data = await res.json();
        if (data.status === "completed") { clearInterval(id); resolve(); }
        else if (data.status === "failed") { clearInterval(id); reject(new Error("Batch translation failed")); }
      } catch (err) {
        clearInterval(id);
        reject(err);
      }
    }, interval);
  });
}

function Select({ label, value, onChange, exclude }: { label: string; value: Lang; onChange: (v: Lang) => void; exclude: Lang }) {
  return (
    <div className="flex-1">
      <label className="block text-xs text-zinc-500 mb-1.5 uppercase tracking-wider">{label}</label>
      <select value={value} onChange={e => onChange(e.target.value as Lang)}
        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2.5 text-sm text-zinc-200 outline-none focus:border-blue-500 transition appearance-none cursor-pointer">
        {LANGS.filter(l => l !== exclude).map(l => (
          <option key={l} value={l}>{LANG_LABELS[l]}</option>
        ))}
      </select>
    </div>
  );
}

export default function App() {
  const [src, setSrc] = useState<Lang>("zh");
  const [tgt, setTgt] = useState<Lang>("en");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const ref = useRef<HTMLInputElement>(null);

  const addFiles = (incoming: FileList | null) => {
    if (!incoming) return;
    const valid = Array.from(incoming).filter(f => /\.(docx|xlsx)$/i.test(f.name));
    if (valid.length) { setFiles(prev => [...prev, ...valid]); setDone(false); }
  };

  const removeFile = (index: number) => setFiles(prev => prev.filter((_, i) => i !== index));

  const translateSingle = async () => {
    const formData = new FormData();
    formData.append("file", files[0]);
    formData.append("source_lang", src);
    formData.append("target_lang", tgt);

    const res = await fetch(`${BE_URL}/api/translate`, { method: "POST", body: formData });
    if (!res.ok) throw new Error("Translation failed");

    const blob = await res.blob();
    downloadBlob(blob, parseFilename(res, files[0].name));
  };

  const translateBatch = async () => {
    const formData = new FormData();
    files.forEach(f => formData.append("files", f));
    formData.append("source_lang", src);
    formData.append("target_lang", tgt);

    const res = await fetch(`${BE_URL}/api/translate/batch`, { method: "POST", body: formData });
    if (!res.ok) throw new Error("Batch submit failed");

    const { job_id } = await res.json();

    await poll(`${BE_URL}/api/translate/batch/${job_id}`, 5000);

    const dlRes = await fetch(`${BE_URL}/api/translate/batch/${job_id}/download`);
    if (!dlRes.ok) throw new Error("Download failed");

    const blob = await dlRes.blob();
    downloadBlob(blob, parseFilename(dlRes, `translated_${job_id}.zip`));
  };

  const translate = async () => {
    setBusy(true);
    setDone(false);

    try {
      if (files.length === 1) await translateSingle();
      else await translateBatch();

      setDone(true);
    } catch (err) {
      console.error(err);
      toast.error("Something went wrong");
    } finally {
      setBusy(false);
      setFiles([]);
    }
  };

  const hidden = files.length - MAX_VISIBLE;

  return (
    <div className="min-h-screen bg-zinc-950 flex items-start justify-center px-4 pt-20 font-sans">
      <div className="w-full max-w-md">
        <h1 className="text-xl font-semibold text-zinc-100 mb-1">File Translate</h1>
        <p className="text-sm text-zinc-500 mb-6">Translate .docx and .xlsx files across languages</p>

        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-5">
          <div className="flex items-end gap-2">
            <Select label="From" value={src} onChange={setSrc} exclude={tgt} />
            <button onClick={() => { setSrc(tgt); setTgt(src); }}
              className="mb-0.5 p-2 rounded-lg border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 transition">
              ⇄
            </button>
            <Select label="To" value={tgt} onChange={setTgt} exclude={src} />
          </div>

          {files.length === 0 ? (
            <div onClick={() => ref.current?.click()}
              onDragOver={e => e.preventDefault()}
              onDrop={e => { e.preventDefault(); addFiles(e.dataTransfer.files); }}
              className="border-2 border-dashed border-zinc-700 rounded-xl p-8 text-center cursor-pointer hover:border-zinc-500 transition">
              <input ref={ref} type="file" accept=".docx,.xlsx" multiple className="hidden" onChange={e => { addFiles(e.target.files); e.target.value = ""; }} />
              <p className="text-sm text-zinc-400">Drop files here or <span className="text-blue-400 underline">browse</span></p>
              <p className="text-xs text-zinc-600 mt-1">.docx or .xlsx only</p>
            </div>
          ) : (
            <div className="space-y-2">
              {files.slice(0, MAX_VISIBLE).map((f, i) => (
                <div key={`${f.name}-${i}`} className="flex items-center gap-3 bg-zinc-800 rounded-xl px-4 py-3">
                  <span className="text-lg">{/\.xlsx$/i.test(f.name) ? "📊" : "📄"}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-zinc-200 truncate">{f.name}</p>
                    <p className="text-xs text-zinc-500">{(f.size / 1024).toFixed(1)} KB</p>
                  </div>
                  <button onClick={() => removeFile(i)} className="text-zinc-500 hover:text-zinc-300 text-lg leading-none">×</button>
                </div>
              ))}

              {hidden > 0 && (
                <p className="text-xs text-zinc-500 pl-1">+{hidden} more file{hidden > 1 ? "s" : ""}</p>
              )}

              <div className="flex items-center gap-3 pt-1">
                <button onClick={() => ref.current?.click()}
                  className="text-xs text-blue-400 hover:text-blue-300 transition">
                  + Add more
                </button>
                <input ref={ref} type="file" accept=".docx,.xlsx" multiple className="hidden" onChange={e => { addFiles(e.target.files); e.target.value = ""; }} />
                <button onClick={() => { setFiles([]); setDone(false); }}
                  className="text-xs text-zinc-500 hover:text-zinc-300 transition">
                  Clear all
                </button>
              </div>
            </div>
          )}

          <div className="flex gap-3">
            <button onClick={translate} disabled={files.length === 0 || busy}
              className="flex-1 bg-blue-600 hover:bg-blue-500 disabled:opacity-30 disabled:pointer-events-none text-white text-sm font-medium rounded-lg py-2.5 transition">
              {busy ? "Translating…" : `Translate${files.length > 1 ? ` (${files.length})` : ""}`}
            </button>
          </div>

          {done && <p className="text-center text-emerald-400 text-sm">✓ Translation complete</p>}
        </div>
      </div>
    </div>
  );
}