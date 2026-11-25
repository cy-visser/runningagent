import { Activity, RotateCcw, Trophy } from "lucide-react";
import type { MeResponse } from "../shared/types";
import { UserMenu } from "./UserMenu";

interface TopBarProps {
  me: MeResponse;
  newSessionDisabled?: boolean;
  onHome: () => void;
  onNewSession: () => void;
  onOpenYearReview?: () => void;
  onViewProfile: () => void;
  onEditProfile: () => void;
  onOpenTrainingPeaks: () => void;
}

export function TopBar({
  me,
  newSessionDisabled = false,
  onHome,
  onNewSession,
  onOpenYearReview,
  onViewProfile,
  onEditProfile,
  onOpenTrainingPeaks,
}: TopBarProps) {
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/90 bg-white/90 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onHome}
            aria-label="AI Running Coach: go to coaching hub"
            title="Back to your coaching hub"
            className="group flex items-center gap-2.5 text-left focus:outline-none cursor-pointer"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-sunset text-white shadow-sm transition group-hover:scale-[1.02] group-active:scale-95">
              <Activity className="h-5 w-5" />
            </span>
            <span className="font-display text-lg font-bold tracking-tight text-slate-900">
              AI Running Coach
            </span>
          </button>
        </div>

        <div className="flex items-center gap-2.5">
          {me.profile_state === "ready" && onOpenYearReview && (
            <div className="group relative">
              <button
                type="button"
                onClick={onOpenYearReview}
                aria-label="Annual Review"
                title="Annual Review"
                className="flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600 shadow-2xs transition hover:border-orange-300 hover:bg-orange-50/70 hover:text-orange-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-400/50 cursor-pointer"
              >
                <Trophy className="h-4 w-4" />
              </button>
              <span
                aria-hidden="true"
                className="pointer-events-none invisible opacity-0 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100 transition-opacity duration-100 absolute left-1/2 top-full mt-2 -translate-x-1/2 z-50 rounded-lg bg-slate-900 px-2.5 py-1 text-xs font-semibold text-slate-50 shadow-lg whitespace-nowrap"
              >
                Annual Review
              </span>
            </div>
          )}

          <button
            type="button"
            onClick={onNewSession}
            disabled={newSessionDisabled}
            className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 shadow-2xs transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">New conversation</span>
          </button>

          <UserMenu
            me={me}
            onViewProfile={onViewProfile}
            onEditProfile={onEditProfile}
            onOpenTrainingPeaks={onOpenTrainingPeaks}
          />
        </div>
      </div>
    </header>
  );
}
