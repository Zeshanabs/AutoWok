"use client";

import { useEffect, useState } from "react";

import { MediaThumbnail } from "@/components/media-thumbnail";
import { ApiError, apiRequest } from "@/lib/api";
import type { MediaAsset } from "@/lib/media-types";

type Props = {
  workspaceId: string;
  initialSelection: string[];
  onClose: () => void;
  onSave: (ids: string[]) => void;
};

/** Mount only while open; selection state initializes from props on mount. */
export function MediaPicker({ workspaceId, initialSelection, onClose, onSave }: Props) {
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [selected, setSelected] = useState<string[]>(initialSelection);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    apiRequest<MediaAsset[]>(`/media-assets?workspace_id=${encodeURIComponent(workspaceId)}`)
      .then((data) => active && (setAssets(data), setError(null)))
      .catch((loadError: unknown) => active && setError(loadError instanceof ApiError ? loadError.message : "Media could not be loaded."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [workspaceId]);

  const toggle = (id: string) =>
    setSelected((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-slate-900/40 p-4 sm:items-center">
      <div role="dialog" aria-modal="true" aria-label="Select media" className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 p-4">
          <h2 className="font-semibold">Select media ({selected.length} selected)</h2>
          <button type="button" onClick={onClose} className="text-sm text-slate-600">Close</button>
        </div>
        <div className="overflow-y-auto p-4">
          {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
          {loading ? (
            <p className="text-sm text-slate-500">Loading media…</p>
          ) : assets.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-300 p-6 text-sm text-slate-600">
              The media library is empty. Upload files from the Media page first.
            </p>
          ) : (
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {assets.map((asset) => {
                const position = selected.indexOf(asset.id);
                return (
                  <li key={asset.id}>
                    <button
                      type="button"
                      aria-pressed={position >= 0}
                      onClick={() => toggle(asset.id)}
                      className={`relative block w-full overflow-hidden rounded-xl border-2 text-left ${position >= 0 ? "border-indigo-600" : "border-transparent"}`}
                    >
                      <MediaThumbnail asset={asset} className="aspect-square w-full" />
                      {position >= 0 && (
                        <span className="absolute left-2 top-2 rounded-full bg-indigo-600 px-2 py-0.5 text-xs font-bold text-white">{position + 1}</span>
                      )}
                      <span className="block truncate p-1.5 text-xs">{asset.title || asset.original_filename}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-200 p-4">
          <button type="button" onClick={onClose} className="rounded-xl border border-slate-300 px-4 py-2 text-sm">Cancel</button>
          <button type="button" onClick={() => onSave(selected)} className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white">Attach selected</button>
        </div>
      </div>
    </div>
  );
}
