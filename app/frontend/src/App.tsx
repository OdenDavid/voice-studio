import { useState } from "react";
import Generate from "./pages/Generate";
import VoiceLibrary from "./pages/VoiceLibrary";
import AudioLibrary from "./pages/AudioLibrary";
import Settings from "./pages/Settings";

type Page = "generate" | "voices" | "library" | "settings";

const NAV: { id: Page; label: string; icon: string }[] = [
  { id: "generate", label: "Generate", icon: "▸" },
  { id: "voices", label: "Voice Library", icon: "◉" },
  { id: "library", label: "Audio Library", icon: "≡" },
  { id: "settings", label: "Settings", icon: "⚙" },
];

export default function App() {
  const [page, setPage] = useState<Page>("generate");

  return (
    <div className="app">
      <nav className="sidebar">
        <div className="brand">
          <span className="brand-dot" />
          Local Voice Studio
        </div>
        {NAV.map((item) => (
          <button
            key={item.id}
            className={`nav-item ${page === item.id ? "active" : ""}`}
            onClick={() => setPage(item.id)}
          >
            <span>{item.icon}</span>
            {item.label}
          </button>
        ))}
        <div className="sidebar-footer">
          CPU-only · offline
          <br />
          Intel macOS build
        </div>
      </nav>
      <main className="content">
        {page === "generate" && <Generate />}
        {page === "voices" && <VoiceLibrary />}
        {page === "library" && <AudioLibrary />}
        {page === "settings" && <Settings />}
      </main>
    </div>
  );
}
