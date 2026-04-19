import { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";

/**
 * Generic form dialog.
 * fields = [{ key, label, type: 'text'|'email'|'number'|'textarea'|'select', options?, required?, default?, placeholder?, help? }]
 * onSubmit(values) -> should throw or resolve. Returns the result.
 */
export default function FormDialog({
  open,
  onOpenChange,
  title,
  description,
  fields = [],
  submitLabel = "Create",
  onSubmit,
  initialValues = {},
  testId = "form-dialog",
}) {
  const [values, setValues] = useState(() => {
    const base = {};
    fields.forEach((f) => { base[f.key] = initialValues[f.key] ?? f.default ?? ""; });
    return base;
  });
  const [submitting, setSubmitting] = useState(false);

  const setField = (k, v) => setValues((s) => ({ ...s, [k]: v }));

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    // Basic validation
    for (const f of fields) {
      if (f.required && (values[f.key] === "" || values[f.key] === null || values[f.key] === undefined)) {
        toast.error(`${f.label} is required`);
        return;
      }
    }
    setSubmitting(true);
    try {
      // Coerce numbers
      const payload = { ...values };
      fields.forEach((f) => {
        if (f.type === "number" && payload[f.key] !== "" && payload[f.key] !== null) {
          payload[f.key] = Number(payload[f.key]);
        }
      });
      await onSubmit(payload);
      onOpenChange(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message || "Operation failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg bg-[var(--surface)] border-[var(--border)] rounded-xl" data-testid={testId}>
        <DialogHeader>
          <DialogTitle className="font-display text-xl">{title}</DialogTitle>
          {description && <p className="text-sm text-[var(--fg-muted)]">{description}</p>}
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 pt-2">
          {fields.map((f) => (
            <div key={f.key} className="space-y-1.5">
              <Label htmlFor={f.key} className="text-xs uppercase tracking-wider text-[var(--fg-muted)]">
                {f.label}{f.required && <span className="text-[var(--danger)] ml-1">*</span>}
              </Label>
              {f.type === "textarea" ? (
                <Textarea id={f.key}
                          placeholder={f.placeholder}
                          value={values[f.key] || ""}
                          onChange={(e) => setField(f.key, e.target.value)}
                          className="bg-[var(--bg)] border-[var(--border)] rounded-md"
                          data-testid={`field-${f.key}`} />
              ) : f.type === "select" ? (
                <Select value={values[f.key] || ""} onValueChange={(v) => setField(f.key, v)}>
                  <SelectTrigger className="bg-[var(--bg)] border-[var(--border)] rounded-md" data-testid={`field-${f.key}`}>
                    <SelectValue placeholder={f.placeholder || "Select…"} />
                  </SelectTrigger>
                  <SelectContent>
                    {f.options?.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input id={f.key}
                       type={f.type || "text"}
                       placeholder={f.placeholder}
                       value={values[f.key] ?? ""}
                       onChange={(e) => setField(f.key, e.target.value)}
                       className="bg-[var(--bg)] border-[var(--border)] rounded-md"
                       data-testid={`field-${f.key}`} />
              )}
              {f.help && <div className="text-[11px] text-[var(--fg-subtle)]">{f.help}</div>}
            </div>
          ))}

          <DialogFooter className="pt-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}
                    className="rounded-full" data-testid="form-cancel">Cancel</Button>
            <Button type="submit" disabled={submitting}
                    className="rounded-full bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white"
                    data-testid="form-submit">
              {submitting ? "Saving…" : submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
