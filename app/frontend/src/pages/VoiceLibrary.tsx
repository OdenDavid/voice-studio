import { useCallback, useEffect, useRef, useState } from "react";
import { api, audioUrl, EngineCapabilities, Job, VoiceRecord } from "../api";

const RECORDING_GUIDANCE = `For the best clone:

1. Record in a quiet room, 10–30 seconds of natural speech.
2. Speak at a steady, conversational pace.
3. Keep a consistent distance from the microphone.
4. Avoid background music, echo and heavy breathing.
5. Use WAV or high-quality MP3/M4A (48 kHz preferred).`;

export default function VoiceLibrary() {
  const [voices, setVoices] = useState<VoiceRecord[]>([]);
  const [engines, setEngines] = useState<EngineCapabilities[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [profileJobs, setProfileJobs] = useState<Record<string, Job>>({});
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [voicesRes, enginesRes] = await Promise.all([
        api.listVoices(),
        api.engines(),
      ]);
      setVoices(voicesRes.voices);
      setEngines(enginesRes.engines);
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [refresh]);

  const upload = async () => {
    setError(null);
    if (!file || !name.trim()) {
      setError("Provide a name and an audio file.");
      return;
    }
    setBusy(true);
    try {
      await api.createVoice(name, description, file);
      setName("");
      setDescription("");
      setFile(null);
      await refresh();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await api.deleteVoice(id);
      await refresh();
    } catch (err) {
      setError(String(err));
    }
  };

  const createProfile = async (voiceId: string, engineId: string) => {
    setError(null);
    try {
      const { job_id } = await api.createVoiceProfile(voiceId, engineId);
      pollRef.current = window.setInterval(async () => {
        try {
          const { job } = await api.job(job_id);
          setProfileJobs((prev) => ({
            ...prev,
            [`${voiceId}:${engineId}`]: job,
          }));
          if (job.status === "done") {
            window.clearInterval(pollRef.current!);
            pollRef.current = null;
            await refresh();
          } else if (job.status === "failed") {
            window.clearInterval(pollRef.current!);
            pollRef.current = null;
            setError(job.error ?? "Profile creation failed.");
          }
        } catch (err) {
          window.clearInterval(pollRef.current!);
          pollRef.current = null;
          setError(String(err));
        }
      }, 900);
    } catch (err) {
      setError(String(err));
    }
  };


  return (
    <div>
      <h1 className="page-title">Voice Library</h1>
      <p className="page-subtitle">
        Upload recordings, name them, and generate engine profiles for cloning.
      </p>

      <div className="card">
        <h3>Recording guidance</h3>
        <div className="hint" style={{ whiteSpace: "pre-line" }}>
          {RECORDING_GUIDANCE}
        </div>
      </div>

      <div className="card">
        <h3>Add voice</h3>
        <div className="row">
          <div className="field">
            <label>Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My voice"
            />
          </div>
          <div className="field">
            <label>Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional notes"
            />
          </div>
        </div>
        <div className="field">
          <label>Recording (WAV, MP3 or M4A)</label>
          <input
            type="file"
            accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
        <button
          className="btn"
          onClick={upload}
          disabled={busy || !file || !name.trim()}
        >
          {busy ? "Uploading…" : "Upload voice"}
        </button>
        {error && <div className="error-box">{error}</div>}
      </div>

      <div className="card">
        <h3>Voices ({voices.length})</h3>
        {voices.length === 0 && (
          <div className="empty">No voices yet. Upload a recording above.</div>
        )}
        {voices.map((voice) => (
          <div className="list-item" key={voice.id}>
            <div className="meta">
              <div className="name">{voice.name}</div>
              <div className="sub">
                {voice.description || voice.original_file} ·{" "}
                {new Date(voice.created_at * 1000).toLocaleDateString()}
              </div>
              <div>
                {engines.map((engine) => {
                  const ready = Boolean(voice.engines?.[engine.engine_id]);
                  const supported = engine.voice_profiles !== false;
                  const job = profileJobs[`${voice.id}:${engine.engine_id}`];
                  const running =
                    job && (job.status === "queued" || job.status === "running");
                  return (
                    <span key={engine.engine_id}>
                      <span className={`tag ${ready ? "ok" : ""}`}>
                        {engine.engine_id}
                        {ready ? " ✓" : " —"}
                      </span>
                      {!ready && supported && (
                        <button
                          className="btn small secondary"
                          disabled={Boolean(running)}
                          onClick={() =>
                            createProfile(voice.id, engine.engine_id)
                          }
                        >
                          {running ? "Working…" : "Create profile"}
                        </button>
                      )}
                      {!supported && (
                        <span className="hint"> (weights lack voice cloning)</span>
                      )}
                    </span>
                  );
                })}
              </div>
            </div>
            <audio controls src={audioUrl.voicePreview(voice.id)} />
            <button className="btn small danger" onClick={() => remove(voice.id)}>
              Delete
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
