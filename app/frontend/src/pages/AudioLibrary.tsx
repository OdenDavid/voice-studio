import { useCallback, useEffect, useState } from "react";
import {
  api,
  audioUrl,
  formatDuration,
  GenerationRecord,
} from "../api";

export default function AudioLibrary() {
  const [generations, setGenerations] = useState<GenerationRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const refresh = useCallback(async () => {
    try {
      const res = await api.listGenerations();
      setGenerations(res.generations);
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const remove = async (id: string) => {
    try {
      await api.deleteGeneration(id);
      await refresh();
    } catch (err) {
      setError(String(err));
    }
  };

  const saveRename = async (id: string) => {
    try {
      await api.renameGeneration(id, renameValue);
      setRenameId(null);
      await refresh();
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <div>
      <h1 className="page-title">Audio Library</h1>
      <p className="page-subtitle">
        Every generation is saved locally. Play, rename, download or delete.
      </p>

      {error && <div className="error-box">{error}</div>}

      <div className="card">
        <h3>Generations ({generations.length})</h3>
        {generations.length === 0 && (
          <div className="empty">
            Nothing here yet — generate something first.
          </div>
        )}
        {generations.map((record) => (
          <div className="list-item" key={record.id}>
            <div className="meta">
              <div className="name">
                {renameId === record.id ? (
                  <span className="row">
                    <input
                      type="text"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void saveRename(record.id);
                      }}
                      style={{ maxWidth: 280 }}
                    />
                    <button
                      className="btn small"
                      onClick={() => saveRename(record.id)}
                    >
                      Save
                    </button>
                  </span>
                ) : (
                  <>
                    {record.name || record.text.slice(0, 60)}
                    <button
                      className="btn small secondary"
                      style={{ marginLeft: 10 }}
                      onClick={() => {
                        setRenameId(record.id);
                        setRenameValue(record.name ?? "");
                      }}
                    >
                      Rename
                    </button>
                  </>
                )}
              </div>
              <div className="sub">
                {new Date(record.created_at * 1000).toLocaleString()} ·{" "}
                {formatDuration(record.duration_seconds)} · {record.engine_id} ·{" "}
                {record.speed.toFixed(2)}×
              </div>
              <div className="sub" style={{ fontStyle: "italic" }}>
                “{record.text.slice(0, 160)}
                {record.text.length > 160 ? "…" : ""}”
              </div>
            </div>
            <audio
              controls
              src={audioUrl.download(
                record.id,
                record.mp3_path ? "mp3" : "wav"
              )}
            />
            <a
              className="btn small"
              href={audioUrl.download(record.id, "wav")}
              download
            >
              WAV
            </a>
            {record.mp3_path && (
              <a
                className="btn small secondary"
                href={audioUrl.download(record.id, "mp3")}
                download
              >
                MP3
              </a>
            )}
            <button
              className="btn small danger"
              onClick={() => remove(record.id)}
            >
              Delete
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
