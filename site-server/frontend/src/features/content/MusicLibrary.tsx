import { useState } from "react";

import { api, errorMessage } from "../../api/client";
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  ErrorBox,
  Input,
  Spinner,
  fa,
} from "../../components/ui";

type Track = {
  id: string;
  title: string;
  creator: string;
  seconds: number;
  url: string;
  page: string;
  licence: string;
  licence_name: string;
  attribution: string;
  needs_credit: boolean;
};

type About = {
  source: string;
  why: string;
  licences: string[];
  excluded: string;
};

/**
 * Free music a shop may actually use. §7
 *
 * Everything shown here is already filtered to licences that permit commercial
 * use — the backend does it, so a track they may not use never appears. A list
 * with a warning label would be a list people scan past.
 *
 * What is *not* hidden is the obligation: a CC-BY track needs a credit line,
 * and the exact wording is shown next to the button that takes it, then stored
 * with the file. A credit the shop cannot find when they publish is a credit
 * that does not get pasted.
 */
export default function MusicLibrary({
  storeId,
  scriptId,
  onPicked,
}: {
  storeId: string | number;
  scriptId: number;
  onPicked: () => void;
}) {
  const [query, setQuery] = useState("");
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [about, setAbout] = useState<About | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [taking, setTaking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function search() {
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.get(
        `/stores/${storeId}/music-library/?q=${encodeURIComponent(query)}`,
      );
      setTracks(data.tracks);
      setAbout(data.about);
      setNote(data.note);
    } catch (err) {
      setError(errorMessage(err));
      setTracks([]);
    } finally {
      setBusy(false);
    }
  }

  async function take(track: Track) {
    setTaking(track.id);
    setError(null);
    try {
      await api.post(`/stores/${storeId}/music-library/`, {
        script_id: scriptId,
        url: track.url,
        licence: track.licence,
        attribution: track.attribution,
      });
      onPicked();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setTaking(null);
    }
  }

  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[14rem] flex-1">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") search();
            }}
            placeholder="دنبال چه حالی می‌گردید؟ مثلاً آرام، پرانرژی، پیانو"
          />
        </div>
        <Button onClick={search} disabled={busy}>
          {busy ? "…" : "جست‌وجو در موسیقی رایگان"}
        </Button>
      </div>

      <ErrorBox message={error} />

      {about && (
        <p className="mt-2 text-xs leading-6" style={{ color: "var(--text-3)" }}>
          منبع: <b>{about.source}</b> — {about.why}
          <br />
          {about.excluded}
        </p>
      )}

      {tracks !== null && (
        tracks.length === 0 ? (
          <EmptyState
            icon="music"
            title="چیزی پیدا نشد"
            description="عبارت دیگری امتحان کنید، یا فایل خودتان را آپلود کنید."
          />
        ) : (
          <>
            {note && (
              <div className="mt-3">
                <Alert tone="info">{note}</Alert>
              </div>
            )}
            <div className="mt-2 flex flex-col gap-2">
              {tracks.map((track) => (
                <div
                  key={track.id}
                  className="rounded-xl p-3"
                  style={{ border: "1px solid var(--line)" }}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-bold" style={{ color: "var(--text)" }}>
                          {track.title}
                        </span>
                        <Badge tone="neutral">{fa(Math.round(track.seconds))}s</Badge>
                        <Badge tone={track.needs_credit ? "warn" : "ok"}>
                          {track.licence_name}
                        </Badge>
                      </div>
                      {track.creator && (
                        <p className="text-xs" style={{ color: "var(--text-3)" }}>
                          {track.creator}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <a href={track.page} target="_blank" rel="noreferrer">
                        <Button variant="ghost">گوش بده</Button>
                      </a>
                      <Button
                        onClick={() => take(track)}
                        disabled={taking !== null}
                      >
                        {taking === track.id ? "…" : "همین را بگذار"}
                      </Button>
                    </div>
                  </div>

                  {track.needs_credit && (
                    <div className="mt-2">
                      <p className="text-xs" style={{ color: "var(--warn)" }}>
                        این آهنگ ذکر منبع لازم دارد. عیناً این را در توضیحات
                        پستتان بنویسید:
                      </p>
                      <code
                        dir="ltr"
                        className="mt-1 block break-all rounded-lg p-2 text-xs"
                        style={{ background: "var(--surface-2)", color: "var(--text-2)" }}
                      >
                        {track.attribution}
                      </code>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )
      )}

      {busy && tracks === null && <Spinner size={18} />}
    </div>
  );
}
