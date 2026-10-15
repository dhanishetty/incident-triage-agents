import { Siren } from "lucide-react";
import ArchitecturePage from "@/features/architecture/ArchitecturePage";

export default function App() {
  return (
    <div className="mx-auto max-w-7xl px-4 pb-16">
      <header className="flex items-center gap-2 py-6 text-lg font-semibold">
        <Siren className="text-azure" />
        <span className="gradient-text">Incident Triage Agents</span>
      </header>
      <main>
        <ArchitecturePage />
      </main>
    </div>
  );
}
