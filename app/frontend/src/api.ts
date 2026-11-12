// Typed REST client for the Local Voice Studio backend.

export interface VoiceRecord {
  id: string;
  name: string;
  description: string;
  original_file: string;
  original_path: string;
  created_at: number;
  engines: Record<string, unknown>;
}

export interface GenerationRecord {
  id: string;
  text: string;
  voice_id: string | null;
  engine_id: string;
  speed: number;
  format: string;
  wav_path: string;
  mp3_path: string | null;
  duration_seconds: number;
  generation_seconds: number;
  sample_rate: number;
  chunks: number;
  created_at: number;
  name?: string;
}

export interface EngineCapabilities {
  engine_id: string;
  display_name: string;
  voice_cloning: boolean;
  voice_profiles: boolean;
  speed_control: boolean;
  streaming: boolean;
  sample_rate: number;
  channels: number;
}

export interface EngineStatus {
  engine_id: string;
  loaded: boolean;
  ready: boolean;
  detail: string;
  model_name: string;
  memory_rss_mb: number;
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed";
  progress: number;
  message: string;
  error: string | null;
  result: { id?: string } | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  // voices
  listVoices: () => request<{ voices: VoiceRecord[] }>("/api/voices"),
  createVoice: (name: string, description: string, file: File) => {
    const form = new FormData();
    form.append("name", name);
    form.append("description", description);
    form.append("file", file);
    return request<{ voice: VoiceRecord }>("/api/voices", {
      method: "POST",
      body: form,
    });
  },
  updateVoice: (id: string, payload: { name?: string; description?: string }) =>
    request<{ voice: VoiceRecord }>(`/api/voices/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteVoice: (id: string) =>
    request<{ ok: boolean }>(`/api/voices/${id}`, { method: "DELETE" }),
  createVoiceProfile: (voiceId: string, engineId: string) =>
    request<{ job_id: string }>(`/api/voices/${voiceId}/profiles/${engineId}`, {
      method: "POST",
    }),
  voiceEngineReady: (voiceId: string, engineId: string) =>
    request<{ ready: boolean; engines: Record<string, unknown> }>(
      `/api/voices/${voiceId}/check/${engineId}`
    ),

  // tts
  generate: (payload: {
    text: string;
    voice_id: string | null;
    engine_id: string;
    speed: number;
    export_format: "wav" | "mp3";
  }) =>
    request<{ job_id: string }>("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  job: (jobId: string) => request<{ job: Job }>(`/api/jobs/${jobId}`),
  engines: () =>
    request<{
      engines: EngineCapabilities[];
      status: Record<string, EngineStatus>;
      default_engine: string;
    }>("/api/engines"),
  loadEngine: (engineId: string) =>
    request<{ status: EngineStatus }>(`/api/engines/${engineId}/load`, {
      method: "POST",
    }),
  unloadEngine: (engineId: string) =>
    request<{ status: EngineStatus }>(`/api/engines/${engineId}/unload`, {
      method: "POST",
    }),

  // library
  listGenerations: () =>
    request<{ generations: GenerationRecord[] }>("/api/library"),
  renameGeneration: (id: string, name: string) =>
    request<{ generation: GenerationRecord }>(`/api/library/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  deleteGeneration: (id: string) =>
    request<{ ok: boolean }>(`/api/library/${id}`, { method: "DELETE" }),

  // settings
  settings: () => request<{ settings: Record<string, unknown> }>("/api/settings"),
  updateSettings: (payload: Record<string, unknown>) =>
    request<{ settings: Record<string, unknown> }>("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  systemInfo: () =>
    request<{
      platform: string;
      machine: string;
      processor: string;
      memory: Record<string, number>;
      data_dir: string;
      models_dir: string;
    }>("/api/settings/system"),
};

export const audioUrl = {
  voicePreview: (voiceId: string) => `/api/voices/${voiceId}/audio`,
  download: (generationId: string, format: "wav" | "mp3") =>
    `/api/library/${generationId}/download?format=${format}`,
};

export function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return "0:00";
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}
