import { useCallback, useEffect, useState } from "react";
import {
  api,
  EngineCapabilities,
  EngineStatus,
} from "../api";

interface SystemInfo {
  platform: string;
  machine: string;
  processor: string;
  memory: Record<string, number>;
  data_dir: string;
  models_dir: string;
}

export default function Settings() {
  const [engines, setEngines] = useState<EngineCapabilities[]>([]);
  const [status, setStatus] = useState<Record<string, EngineStatus>>({});
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [enginesRes, systemRes] = await Promise.all([
        api.engines(),
        api.systemInfo(),
      ]);
      setEngines(enginesRes.engines);
      setStatus(enginesRes.status as unknown as Record<string, EngineStatus>);
      setSystem(systemRes);
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const load = async (engineId: string) => {
    setError(null);
    try {
      const res = await api.loadEngine(engineId);
      setStatus((prev) => ({ ...prev, [engineId]: res.status }));
    } catch (err) {
      setError(String(err));
    }
  };

  const unload = async (engineId: string) => {
    setError(null);
    try {
      const res = await api.unloadEngine(engineId);
      setStatus((prev) => ({ ...prev, [engineId]: res.status }));
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="page-subtitle">
        Engine management and system information.
      </p>

      {error && <div className="error-box">{error}</div>}

      <div className="card">
        <h3>Engines</h3>
        {engines.map((engine) => {
          const engineStatus = status[engine.engine_id];
          return (
            <div className="list-item" key={engine.engine_id}>
              <div className="meta">
                <div className="name">{engine.display_name}</div>
                <div className="sub">
                  <span className={`tag ${engineStatus?.ready ? "ok" : ""}`}>
                    {engineStatus?.ready ? "ready" : "not loaded"}
                  </span>
                  {engine.voice_cloning && <span className="tag">cloning</span>}
                  <span className="tag">{engine.sample_rate} Hz</span>
                </div>
              </div>
              {engineStatus?.ready ? (
                <button
                  className="btn small secondary"
                  onClick={() => unload(engine.engine_id)}
                >
                  Unload
                </button>
              ) : (
                <button
                  className="btn small"
                  onClick={() => load(engine.engine_id)}
                >
                  Load
                </button>
              )}
            </div>
          );
        })}
        <div className="hint">
          Only one engine stays loaded at a time to keep memory usage low.
        </div>
      </div>

      {system && (
        <div className="card">
          <h3>System</h3>
          <dl className="kv">
            <dt>Platform</dt>
            <dd>{system.platform}</dd>
            <dt>Architecture</dt>
            <dd>{system.machine}</dd>
            <dt>CPU</dt>
            <dd>{system.processor}</dd>
            {system.memory.free_mb !== undefined && (
              <>
                <dt>Free memory</dt>
                <dd>{system.memory.free_mb} MB</dd>
              </>
            )}
            <dt>Data directory</dt>
            <dd>{system.data_dir}</dd>
            <dt>Models directory</dt>
            <dd>{system.models_dir}</dd>
          </dl>
        </div>
      )}
    </div>
  );
}
