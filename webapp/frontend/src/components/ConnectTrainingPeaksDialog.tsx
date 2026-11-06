import { useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Lock,
  X,
} from "lucide-react";
import { connectTrainingPeaks } from "../lib/api";
import type { ConnectTpResponse, TrainingPeaksStatus } from "../types";

interface ConnectTrainingPeaksDialogProps {
  open: boolean;
  tpStatus: TrainingPeaksStatus;
  onClose: () => void;
  onConnected: (res: ConnectTpResponse) => void;
}

export function ConnectTrainingPeaksDialog({
  open,
  tpStatus,
  onClose,
  onConnected,
}: ConnectTrainingPeaksDialogProps) {
  const [cookie, setCookie] = useState("");
  const [reveal, setReveal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successInfo, setSuccessInfo] = useState<ConnectTpResponse | null>(null);

  if (!open) return null;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = cookie.trim();
    if (!trimmed) {
      setError("Paste your Production_tpAuth cookie value first.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await connectTrainingPeaks(trimmed);
      setSuccessInfo(result);
      setCookie("");
      onConnected(result);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not validate TrainingPeaks cookie.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-xs"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tp-dialog-title"
    >
      <div className="w-full max-w-lg overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-2xl">
        <div
          className="flex items-start justify-between border-b border-orange-200/70 px-6 py-5"
          style={{
            backgroundImage: "linear-gradient(135deg, #FFEDD5 0%, #FCE7F3 100%)",
          }}
        >
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-sunset text-white shadow-sm">
              <KeyRound className="h-5 w-5" />
            </span>
            <div>
              <h2
                id="tp-dialog-title"
                className="font-display text-lg font-bold text-slate-900"
              >
                {tpStatus.connected
                  ? "TrainingPeaks Connection"
                  : "Connect TrainingPeaks"}
              </h2>
              <p className="text-xs text-slate-600">
                Encrypted with Cloud KMS and bound exclusively to your profile
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded-full bg-white/80 p-1.5 text-slate-500 transition hover:bg-white hover:text-slate-900 cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 p-6">
          {tpStatus.connected && !successInfo && (
            <div className="flex items-center justify-between rounded-2xl border border-emerald-200 bg-emerald-50/70 px-4 py-3 text-xs text-emerald-900">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
                <div>
                  <p className="font-semibold">
                    Connected{tpStatus.tp_name ? ` as ${tpStatus.tp_name}` : ""}
                  </p>
                  {tpStatus.tp_athlete_id && (
                    <p className="text-emerald-700">
                      Athlete ID #{tpStatus.tp_athlete_id}
                    </p>
                  )}
                </div>
              </div>
              <span className="rounded-full bg-white px-2.5 py-0.5 text-[11px] font-medium text-emerald-700 border border-emerald-200">
                Active
              </span>
            </div>
          )}

          {successInfo && (
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3.5 text-sm text-emerald-900">
              <div className="flex items-center gap-2 font-semibold">
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                <span>
                  Verified TrainingPeaks account
                  {successInfo.tp.tp_name ? ` (${successInfo.tp.tp_name})` : ""}!
                </span>
              </div>
              <p className="mt-1 text-xs text-emerald-700">
                Your credential is encrypted in Firestore via Cloud KMS.
              </p>
            </div>
          )}

          <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 text-xs text-slate-600 space-y-1.5">
            <p className="font-semibold text-slate-800">
              How to copy your <code className="rounded bg-white px-1.5 py-0.5 text-orange-700 border border-slate-200">Production_tpAuth</code> cookie:
            </p>
            <ol className="list-decimal pl-4 space-y-1">
              <li>
                Sign in at{" "}
                <span className="font-medium text-slate-800">
                  app.trainingpeaks.com
                </span>{" "}
                in Chrome.
              </li>
              <li>
                Open DevTools (<kbd className="rounded border border-slate-300 bg-white px-1">F12</kbd>) →{" "}
                <strong>Application</strong> → <strong>Cookies</strong> →{" "}
                <code>https://app.trainingpeaks.com</code>.
              </li>
              <li>
                Select <code className="font-semibold text-slate-800">Production_tpAuth</code> and copy its <strong>Value</strong>.
              </li>
            </ol>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label
                htmlFor="tp-cookie-input"
                className="text-xs font-semibold text-slate-700"
              >
                {tpStatus.connected
                  ? "Replace Production_tpAuth cookie"
                  : "Production_tpAuth cookie value"}
              </label>
              <button
                type="button"
                onClick={() => setReveal((v) => !v)}
                className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800 cursor-pointer"
              >
                {reveal ? (
                  <>
                    <EyeOff className="h-3.5 w-3.5" /> Hide
                  </>
                ) : (
                  <>
                    <Eye className="h-3.5 w-3.5" /> Show
                  </>
                )}
              </button>
            </div>
            <input
              id="tp-cookie-input"
              type={reveal ? "text" : "password"}
              value={cookie}
              onChange={(e) => setCookie(e.target.value)}
              placeholder="Paste Production_tpAuth value…"
              autoComplete="off"
              spellCheck={false}
              className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 font-mono text-xs text-slate-900 placeholder:text-slate-400 focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-400/30"
            />
            <p className="mt-1.5 flex items-center gap-1 text-[11px] text-slate-500">
              <Lock className="h-3 w-3 text-slate-400" />
              Validated live against TrainingPeaks before KMS envelope encryption.
            </p>
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-xs text-rose-800">
              <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex items-center justify-end gap-2.5 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 cursor-pointer"
            >
              {successInfo ? "Done" : "Cancel"}
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex items-center gap-2 rounded-xl bg-sunset bg-sunset-hover px-5 py-2 text-xs font-semibold text-white shadow-sunset transition disabled:opacity-60 cursor-pointer"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Validating…
                </>
              ) : tpStatus.connected ? (
                "Validate & Update Cookie"
              ) : (
                "Validate & Connect"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
