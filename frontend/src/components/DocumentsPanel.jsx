import { useEffect, useRef, useState } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Upload, Download, Trash, File as FileIcon, FilePdf, Image as ImageIcon } from "@phosphor-icons/react";
import { fmtDate } from "@/lib/format";

const DOC_TYPES = [
  { value: "kyc", label: "KYC" },
  { value: "kyb", label: "KYB" },
  { value: "contract", label: "Contract" },
  { value: "other", label: "Other" },
];

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.csv";
const MAX_MB = 10;

function bytes(n) {
  if (!n && n !== 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function iconFor(ct = "") {
  if (ct.startsWith("image/")) return ImageIcon;
  if (ct.includes("pdf")) return FilePdf;
  return FileIcon;
}

export default function DocumentsPanel({ orgId, caseId, canUpload = true, canDelete = true, title = "Documents" }) {
  const [docs, setDocs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [docType, setDocType] = useState("kyc");
  const inputRef = useRef(null);

  const load = async () => {
    const params = {};
    if (orgId) params.org_id = orgId;
    if (caseId) params.case_id = caseId;
    const { data } = await api.get("/documents", { params });
    setDocs(data.items || []);
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [orgId, caseId]);

  const handleFiles = async (files) => {
    if (!files || files.length === 0) return;
    for (const file of files) {
      if (file.size > MAX_MB * 1024 * 1024) {
        toast.error(`${file.name} exceeds ${MAX_MB} MB`);
        continue;
      }
      const form = new FormData();
      form.append("file", file);
      if (orgId) form.append("org_id", orgId);
      if (caseId) form.append("case_id", caseId);
      form.append("doc_type", docType);
      try {
        setBusy(true);
        await api.post("/documents/upload", form, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        toast.success(`${file.name} uploaded`);
      } catch (e) {
        toast.error(e?.response?.data?.detail || `Upload failed: ${file.name}`);
      } finally {
        setBusy(false);
      }
    }
    await load();
  };

  const onDrop = (e) => {
    e.preventDefault();
    handleFiles(e.dataTransfer.files);
  };

  const onDownload = async (doc) => {
    try {
      const { data } = await api.get(`/documents/${doc.document_id}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(data);
      const a = document.createElement("a");
      a.href = url;
      a.download = doc.original_filename || doc.document_id;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (e) {
      toast.error("Download failed");
    }
  };

  const onDelete = async (doc) => {
    if (!window.confirm(`Delete ${doc.original_filename}?`)) return;
    try {
      await api.delete(`/documents/${doc.document_id}`);
      toast.success("Deleted");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    }
  };

  return (
    <div className="prosper-card p-5" data-testid="documents-panel">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-[10px] uppercase tracking-[0.15em] text-[var(--fg-muted)] font-mono">Compliance</div>
          <h3 className="font-display font-bold text-lg">{title}</h3>
        </div>
        <div className="text-xs text-[var(--fg-muted)] font-mono">{docs.length} files</div>
      </div>

      {canUpload && (
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={onDrop}
          className="border border-dashed border-[var(--border)] rounded-lg p-5 mb-4 text-center bg-[var(--surface)]"
          data-testid="documents-dropzone"
        >
          <Upload size={20} weight="bold" className="mx-auto mb-2 text-[var(--primary)]" />
          <div className="text-sm text-[var(--fg)] mb-1">
            Drag & drop files here, or{" "}
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="text-[var(--primary)] underline underline-offset-2"
              data-testid="documents-browse-btn"
            >
              browse
            </button>
          </div>
          <div className="text-xs text-[var(--fg-muted)] font-mono">
            PDF · PNG · JPG · WebP · CSV · max {MAX_MB} MB
          </div>
          <div className="flex items-center justify-center gap-2 mt-3">
            <label className="text-[10px] uppercase tracking-wider text-[var(--fg-muted)] font-mono">Type</label>
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
              className="text-xs font-mono bg-[var(--bg)] border border-[var(--border)] rounded px-2 py-1 text-[var(--fg)]"
              data-testid="documents-type-select"
            >
              {DOC_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            multiple
            className="hidden"
            onChange={(e) => handleFiles(e.target.files)}
            data-testid="documents-file-input"
          />
          {busy && (
            <div className="text-xs text-[var(--primary)] mt-2 font-mono">Uploading…</div>
          )}
        </div>
      )}

      {docs.length === 0 ? (
        <div className="text-sm text-[var(--fg-muted)] text-center py-6">No documents yet.</div>
      ) : (
        <div className="divide-y divide-[var(--border)]">
          {docs.map((d) => {
            const Icon = iconFor(d.content_type);
            return (
              <div
                key={d.document_id}
                className="flex items-center gap-3 py-3"
                data-testid={`document-row-${d.document_id}`}
              >
                <Icon size={22} weight="duotone" className="text-[var(--primary)] shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-[var(--fg)] truncate">{d.original_filename}</div>
                  <div className="text-xs text-[var(--fg-muted)] font-mono">
                    {d.doc_type?.toUpperCase() || "DOC"} · {bytes(d.size)} · {fmtDate(d.created_at)}
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onDownload(d)}
                  className="h-8 px-2 rounded-sm"
                  data-testid={`document-download-${d.document_id}`}
                >
                  <Download size={13} />
                </Button>
                {canDelete && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onDelete(d)}
                    className="h-8 px-2 rounded-sm border-[var(--danger)]/30 text-[var(--danger)]"
                    data-testid={`document-delete-${d.document_id}`}
                  >
                    <Trash size={13} />
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
