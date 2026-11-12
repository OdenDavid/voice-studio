import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  audioUrl,
  EngineCapabilities,
  GenerationRecord,
  Job,
  VoiceRecord,
} from "../api";

export default function Generate() {
  const [text, setText] = useState("");
  const [voices, setVoices] = useState<VoiceRecord[]>([]);
  const [engines, setEngines] = useState<EngineCapabilities[]>([]);
  const [engineStatuses, setEngineStatuses] = useState<Record<string, unknown>>({});
  const [voiceId, setVoiceId] = useState<string>("");
  const [engineId, setEngineId] = useState<string>("moss");
  const [speed, setSpeed] = useState(1.0);
  const [format, setFormat] = useState<"wav" | "mp3">("wav");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerationRecord | null>(null);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [voicesRes, enginesRes] = await Promise.all([
        api.listVoices(),
        api.engines(),
      ]);
      setVoices(voicesRes.voices);
      setEngines(enginesRes.engines);
      setEngineStatuses(enginesRes.status);
      setEngineId((current) => current || enginesRes.default_engine);
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

  const pollJob = useCallback((jobId: string) => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      try {
        const { job } = await api.job(jobId);
        setJob(job);
        if (job.status === "done" && job.result?.id) {
          window.clearInterval(pollRef.current!);
          pollRef.current = null;
          const { generations } = await api.listGenerations();
          const record = generations.find((g) => g.id === job.result!.id);
          setResult(record ?? null);
        } else if (job.status === "failed") {
          window.clearInterval(pollRef.current!);
          pollRef.current = null;
          setError(job.error ?? "Generation failed.");
        }
      } catch (err) {
        window.clearInterval(pollRef.current!);
        pollRef.current = null;
        setError(String(err));
      }
    }, 900);
  }, []);

  const generate = async () => {
    setError(null);
    setResult(null);
    try {
      const { job_id } = await api.generate({
        text,
        voice_id: voiceId || null,
        engine_id: engineId,
        speed,
        export_format: format,
      });
      setJob({
        id: job_id,
        status: "queued",
        progress: 0,
        message: "Queued",
      } as Job);
      pollJob(job_id);
    } catch (err) {
      setError(String(err));
    }
  };


  const busy =
    job !== null && (job.status === "queued" || job.status === "running");
  const selectedEngine = engines.find((e) => e.engine_id === engineId);
  const engineStatus = engineStatuses[engineId] as
    | { ready?: boolean; detail?: string }
    | undefined;

  return (
    <div>
      <h1 className="page-title">Generate</h1>
      <p className="page-subtitle">
        Convert text to speech with your cloned voice — fully offline.
      </p>

      <div className="card">
        <h3>Script</h3>
        <div className="field">
          <div className="textarea-wrap">
            <textarea
              className="generate-textarea"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Type or paste the text you want to turn into speech…"
            />
            <span className="char-counter">{text.length} chars</span>
          </div>
        </div>

        <div className="row">
          <div className="field">
            <label>Voice</label>
            <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
              <option value="">— Built-in voice —</option>
              {voices.map((voice) => (
                <option key={voice.id} value={voice.id}>
                  {voice.name}
                </option>
              ))}
            </select>
            {voices.length === 0 && (
              <div className="hint">
                No voices yet — create one in the Voice Library.
              </div>
            )}
          </div>
          <div className="field">
            <label>Model</label>
            <select value={engineId} onChange={(e) => setEngineId(e.target.value)}>
              {engines.map((engine) => (
                <option
                  key={engine.engine_id}
                  value={engine.engine_id}
                  disabled={engine.voice_cloning === false}
                >
                  {engine.display_name}
                  {engine.voice_cloning === false ? " — unavailable" : ""}
                </option>
              ))}
            </select>
            <div className="hint">
              {selectedEngine
                ? `${selectedEngine.sample_rate} Hz · ${
                    engineStatus?.ready ? "ready" : "loads on demand"
                  }`
                : ""}
            </div>
          </div>
        </div>

        <div className="row">
          <div className="field">
            <label>Speed</label>
            <div className="slider-row">
              <input
                type="range"
                min={0.5}
                max={2}
                step={0.05}
                value={speed}
                onChange={(e) => setSpeed(Number(e.target.value))}
              />
              <span className="slider-value">{speed.toFixed(2)}×</span>
            </div>
          </div>
          <div className="field">
            <label>Export</label>
            <div className="toggle-group">
              <button
                className={format === "wav" ? "active" : ""}
                onClick={() => setFormat("wav")}
              >
                WAV
              </button>
              <button
                className={format === "mp3" ? "active" : ""}
                onClick={() => setFormat("mp3")}
              >
                MP3
              </button>
            </div>
          </div>
        </div>

        <button
          className="btn"
          onClick={generate}
          disabled={!text.trim() || busy}
        >
          {busy ? "Generating…" : "Generate"}
        </button>

        {job && (
          <div>
            <div className="progress-track">
              <div
                className="progress-fill"
                style={{ width: `${Math.round(job.progress * 100)}%` }}
              />
            </div>
            <div className="status-line">
              <span>
                {job.status === "running"
                  ? job.message
                  : job.status === "done"
                    ? "Finished"
                    : job.status === "failed"
                      ? "Failed"
                      : "Queued"}
              </span>
              <span>{Math.round(job.progress * 100)}%</span>
            </div>
          </div>
        )}

        {error && <div className="error-box">{error}</div>}

        {result && (
          <div className="card">
            <h3>Result</h3>
            <audio controls src={audioUrl.download(result.id, format)} />
            <div className="status-line">
              <span>
                {result.duration_seconds.toFixed(1)}s audio ·{" "}
                {result.generation_seconds.toFixed(1)}s generation ·{" "}
                {result.chunks} chunk{result.chunks === 1 ? "" : "s"}
              </span>
            </div>
            <a
              className="btn small"
              href={audioUrl.download(result.id, format)}
              download
            >
              Download {format.toUpperCase()}
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
