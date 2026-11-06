import { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Link2,
  LogOut,
  Pencil,
  ShieldCheck,
  User,
} from "lucide-react";
import type { MeResponse } from "../shared/types";

interface UserMenuProps {
  me: MeResponse;
  onViewProfile: () => void;
  onEditProfile: () => void;
  onOpenTrainingPeaks: () => void;
}

export function UserMenu({
  me,
  onViewProfile,
  onEditProfile,
  onOpenTrainingPeaks,
}: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handleOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  const hasProfile = me.profile_state !== "none";

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-2.5 rounded-full border border-slate-200 bg-white py-1 pl-1.5 pr-3 text-left shadow-xs transition hover:border-slate-300 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-orange-400/50 cursor-pointer"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-sunset font-display text-xs font-bold tracking-tight text-white shadow-xs">
          {me.initials}
        </span>
        <span className="hidden sm:flex flex-col leading-tight">
          <span className="text-xs font-semibold text-slate-900">
            {me.display_name}
          </span>
          <span className="text-[11px] text-slate-500">
            {me.tp.connected ? "TP Connected" : "Connect TP"}
          </span>
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-2 w-72 origin-top-right rounded-2xl border border-slate-200 bg-white p-1.5 shadow-xl"
        >
          <div className="rounded-xl bg-slate-50 px-3.5 py-2.5 mb-1">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate text-sm font-semibold text-slate-900">
                {me.display_name}
              </p>
              <span className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-[10px] font-medium text-slate-600 border border-slate-200">
                <ShieldCheck className="h-3 w-3 text-orange-500" />
                IAM
              </span>
            </div>
            <p className="truncate text-xs text-slate-500 mt-0.5">{me.email}</p>
          </div>

          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              if (hasProfile) {
                onViewProfile();
              } else {
                onOpenTrainingPeaks();
              }
            }}
            className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 hover:text-slate-900 cursor-pointer"
          >
            <User className="h-4 w-4 text-slate-500" />
            <span className="font-medium">View profile</span>
          </button>

          <button
            type="button"
            role="menuitem"
            disabled={!hasProfile}
            onClick={() => {
              setOpen(false);
              onEditProfile();
            }}
            className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-45 cursor-pointer"
          >
            <Pencil className="h-4 w-4 text-slate-500" />
            <span className="font-medium">Edit profile</span>
          </button>

          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onOpenTrainingPeaks();
            }}
            className="flex w-full items-center justify-between rounded-xl px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 hover:text-slate-900 cursor-pointer"
          >
            <span className="flex items-center gap-2.5">
              <Link2 className="h-4 w-4 text-slate-500" />
              <span className="font-medium">TrainingPeaks</span>
            </span>
            {me.tp.connected ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 border border-emerald-200">
                <CheckCircle2 className="h-3 w-3" />
                Active
              </span>
            ) : (
              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700 border border-amber-200">
                Setup
              </span>
            )}
          </button>

          <div className="my-1 border-t border-slate-100" />

          <a
            href="/_gcp_iap/clear_login_cookie"
            role="menuitem"
            className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-medium text-rose-600 transition hover:bg-rose-50"
          >
            <LogOut className="h-4 w-4" />
            <span>Sign out</span>
          </a>
        </div>
      )}
    </div>
  );
}
