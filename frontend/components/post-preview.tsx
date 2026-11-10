/* eslint-disable @next/next/no-img-element -- authenticated API media */
"use client";

import { useState } from "react";

import { MediaThumbnail } from "@/components/media-thumbnail";
import { mediaUrl, type DraftPreview } from "@/lib/media-types";

function Avatar({ preview }: { preview: DraftPreview }) {
  return preview.account_image_url ? (
    <img src={preview.account_image_url} alt="" className="h-9 w-9 rounded-full object-cover" />
  ) : (
    <span className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-200 text-sm font-bold text-slate-600">
      {(preview.account_name ?? "A").slice(0, 1).toUpperCase()}
    </span>
  );
}

function Caption({ text, clampAt }: { text: string; clampAt: number }) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return null;
  const long = text.length > clampAt;
  return (
    <p className="whitespace-pre-wrap break-words text-sm">
      {long && !expanded ? `${text.slice(0, clampAt)}… ` : text}
      {long && (
        <button type="button" onClick={() => setExpanded(!expanded)} className="text-slate-500">
          {expanded ? " less" : "more"}
        </button>
      )}
    </p>
  );
}

export function PostPreview({ preview }: { preview: DraftPreview }) {
  const [slide, setSlide] = useState(0);
  const caption = preview.caption ?? "";
  const media = preview.media;
  const current = media[Math.min(slide, Math.max(0, media.length - 1))];

  if (preview.platform === "instagram") {
    return (
      <figure className="mx-auto w-full max-w-sm overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center gap-2 p-3">
          <Avatar preview={preview} />
          <span className="text-sm font-semibold">{preview.account_username ?? preview.account_name ?? "your_account"}</span>
        </div>
        <div className="relative aspect-square bg-slate-100">
          {current ? (
            <MediaThumbnail asset={{ ...current, thumbnail_url: current.media_type === "video" ? null : current.thumbnail_url }} controls={current.media_type === "video"} className="h-full w-full" />
          ) : (
            <p className="flex h-full items-center justify-center p-6 text-center text-sm text-slate-500">Instagram requires an image or video.</p>
          )}
          {media.length > 1 && (
            <>
              <span className="absolute right-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-xs text-white">{slide + 1}/{media.length}</span>
              <div className="absolute inset-x-0 bottom-2 flex justify-center gap-1">
                {media.map((item, index) => (
                  <button key={item.id} type="button" aria-label={`Show item ${index + 1}`} onClick={() => setSlide(index)} className={`h-1.5 w-1.5 rounded-full ${index === slide ? "bg-white" : "bg-white/50"}`} />
                ))}
              </div>
            </>
          )}
        </div>
        <figcaption className="space-y-1 p-3">
          <p className="text-sm"><span className="font-semibold">{preview.account_username ?? "your_account"}</span></p>
          <Caption text={caption} clampAt={125} />
        </figcaption>
      </figure>
    );
  }

  return (
    <figure className="mx-auto w-full max-w-lg overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center gap-2 p-3">
        <Avatar preview={preview} />
        <div>
          <p className="text-sm font-semibold">{preview.account_name ?? "Your Page"}</p>
          <p className="text-xs text-slate-500">Just now · Public</p>
        </div>
      </div>
      <div className="px-3 pb-3"><Caption text={caption} clampAt={480} /></div>
      {media.length === 1 && media[0].media_type === "video" ? (
        <video src={mediaUrl(media[0].content_url)} controls className="w-full bg-black" />
      ) : media.length === 1 ? (
        <MediaThumbnail asset={{ ...media[0], thumbnail_url: null }} className="w-full" />
      ) : media.length > 1 ? (
        <div className="grid grid-cols-2 gap-0.5">
          {media.slice(0, 4).map((item, index) => (
            <div key={item.id} className="relative aspect-square">
              <MediaThumbnail asset={item} className="h-full w-full" />
              {index === 3 && media.length > 4 && (
                <span className="absolute inset-0 flex items-center justify-center bg-black/50 text-2xl font-bold text-white">+{media.length - 4}</span>
              )}
            </div>
          ))}
        </div>
      ) : null}
      <div className="flex justify-around border-t border-slate-100 p-2 text-xs text-slate-500">
        <span>Like</span><span>Comment</span><span>Share</span>
      </div>
    </figure>
  );
}
