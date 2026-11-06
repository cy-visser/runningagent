import { Activity, RotateCcw, Target } from "lucide-react";
import type { MeResponse } from "../types";
import { UserMenu } from "./UserMenu";

interface TopBarProps {
  me: MeResponse;
  hasMessages: boolean;
  onHome: () => void;
  onNewSession: () => void;
  onViewProfile: () => void;
  onEditProfile: () => void;
  onOpenTrainingPeaks: () => void;
}

export function TopBar({
  me,
  hasMessages,
  onHome,
  onNewSession,
  onViewProfile,
  onEditProfile,
  onOpenTrainingPeaks,
}: TopBarProps) {
  const activeGoal = me.summary?.active_goal;

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/90 bg-white/90 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onHome}
            className="group flex items-center gap-2.5 text-left focus:outline-none cursor-pointer"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-sunset text-white shadow-sm transition group-hover:scale-[1.02]">
              <Activity className="h-5 w-5" />
            </span>
            <div>
              <span className="font-display text-base font-bold tracking-tight text-slate-900">
                AI Running Coach
              </span>
              <span className="hidden md:inline-block ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-800 border border-slate-300">
                Performance Lab
              </span>
            </div>
          </button>

          {activeGoal && (
            <button
              type="button"
              onClick={onViewProfile}
              className="hidden lg:inline-flex items-center gap-1.5 rounded-full border border-rose-300 bg-rose-100/85 px-3 py-1 text-xs font-semibold text-rose-950 transition hover:border-rose-400 hover:bg-rose-200/75 cursor-pointer"
            >
              <Target className="h-3.5 w-3.5 text-rose-700" />
              <span>{activeGoal}</span>
              {me.summary?.weeks_remaining != null && (
                <span className="text-rose-800/85 font-medium">
                  · {me.summary.weeks_remaining}w
                </span>
              )}
            </button>
          )}
        </div>

        <div className="flex items-center gap-2.5">
          {hasMessages && (
            <button
              type="button"
              onClick={onNewSession}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-2xs transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 cursor-pointer"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">New conversation</span>
            </button>
          )}

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
