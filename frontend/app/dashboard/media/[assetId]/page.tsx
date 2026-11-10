"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { MediaThumbnail } from "@/components/media-thumbnail";
import { AppShell, ProtectedPage } from "@/components/route-guards";
import { ApiError, apiRequest } from "@/lib/api";
import type { Brand } from "@/lib/brand-types";
import { formatBytes, formatDuration, mediaUrl, type MediaAsset } from "@/lib/media-types";

const fieldClass = "w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-indigo-500";

export default function MediaAssetPage() {
  const { assetId } = useParams<{ assetId: string }>();
  const router = useRouter();
  const { selectedWorkspace } = useAuth();
  const [asset, setAsset] = useState<MediaAsset | null>(null);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [title, setTitle] = useState("");
  const [brandId, setBrandId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [loadedId, setLoadedId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    apiRequest<MediaAsset>(`/media-assets/${assetId}`)
      .then(async (data) => {
        const brandData = await apiRequest<Brand[]>(`/workspaces/${data.workspace_id}/brands`).catch(() => []);
        if (!active) return;
        setAsset(data);
        setBrands(brandData);
        setTitle(data.title ?? "");
        setBrandId(data.brand_id ?? "");
        setLoadedId(assetId);
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        setError(loadError instanceof ApiError ? loadError.message : "The media asset could not be loaded.");
        setLoadedId(assetId);
      });
    return () => {
      active = false;
    };
  }, [assetId]);

  const save = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await apiRequest<MediaAsset>(`/media-assets/${assetId}`, {
        method: "PATCH",
        body: JSON.stringify({ title: title.trim() || null, brand_id: brandId || null }),
      });
      setAsset(updated);
      setNotice("Details saved.");
    } catch (saveError) {
      setError(saveError instanceof ApiError ? saveError.message : "The details could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  const archive = async () => {
    setBusy(true);
    try {
      await apiRequest(`/media-assets/${assetId}`, { method: "DELETE" });
      router.push("/dashboard/media");
    } catch (archiveError) {
      setError(archiveError instanceof ApiError ? archiveError.message : "The asset could not be archived.");
      setConfirmArchive(false);
      setBusy(false);
    }
  };

  return (
    <ProtectedPage>
      <AppShell>
        <Link href="/dashboard/media" className="text-sm font-semibold text-indigo-700">← Media library</Link>
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
        {notice && <p role="status" className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
        {loadedId !== assetId ? (
          <p className="mt-6 text-sm text-slate-500">Loading media…</p>
        ) : asset ? (
          <div className="mt-6 grid gap-6 lg:grid-cols-[3fr_2fr]">
            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
              <MediaThumbnail
                asset={{ ...asset, thumbnail_url: null }}
                controls
                className="max-h-[70vh] w-full object-contain"
              />
            </div>
            <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
              <h1 className="break-words text-xl font-bold">{asset.title || asset.original_filename}</h1>
              {asset.archived && <p className="rounded-lg bg-zinc-100 p-2 text-sm">This asset is archived.</p>}
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div><dt className="text-slate-500">File name</dt><dd className="break-all">{asset.original_filename}</dd></div>
                <div><dt className="text-slate-500">Type</dt><dd>{asset.mime_type}</dd></div>
                <div><dt className="text-slate-500">Size</dt><dd>{formatBytes(asset.file_size)}</dd></div>
                <div><dt className="text-slate-500">Dimensions</dt><dd>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : "Unknown"}</dd></div>
                {asset.duration_seconds != null && <div><dt className="text-slate-500">Duration</dt><dd>{formatDuration(asset.duration_seconds)}</dd></div>}
                <div><dt className="text-slate-500">Uploaded</dt><dd>{new Date(asset.created_at).toLocaleString()}</dd></div>
                <div><dt className="text-slate-500">Metadata</dt><dd>{asset.metadata_stripped ? "EXIF removed" : "Unchanged"}</dd></div>
                <div><dt className="text-slate-500">Storage</dt><dd>{asset.storage_provider} · {asset.processing_status}</dd></div>
              </dl>
              {!asset.archived && (
                <>
                  <label className="block space-y-1 text-sm font-medium text-slate-700">
                    Title
                    <input className={fieldClass} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
                  </label>
                  <label className="block space-y-1 text-sm font-medium text-slate-700">
                    Brand
                    <select className={fieldClass} value={brandId} onChange={(e) => setBrandId(e.target.value)}>
                      <option value="">No brand</option>
                      {brands.map((brand) => <option key={brand.id} value={brand.id}>{brand.name}</option>)}
                    </select>
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={() => void save()} disabled={busy} className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-300">Save details</button>
                    <a href={mediaUrl(asset.download_url)} className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium">Download</a>
                    <button type="button" onClick={() => setConfirmArchive(true)} disabled={busy} className="rounded-xl border border-red-300 px-4 py-2 text-sm font-medium text-red-700">Archive</button>
                  </div>
                </>
              )}
              {selectedWorkspace && selectedWorkspace.id !== asset.workspace_id && (
                <p className="text-xs text-amber-700">This asset belongs to a different workspace than the one selected.</p>
              )}
            </section>
          </div>
        ) : null}
        <ConfirmDialog
          open={confirmArchive}
          title="Archive this media?"
          confirmLabel="Archive"
          tone="danger"
          busy={busy}
          onCancel={() => setConfirmArchive(false)}
          onConfirm={() => void archive()}
        >
          <p>Archived media is hidden from the library and cannot be published.</p>
        </ConfirmDialog>
      </AppShell>
    </ProtectedPage>
  );
}
