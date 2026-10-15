import type { RunView } from "./FlowDiagram";
import type { Scenario } from "./scenarios";

export interface LogLine {
  time: string;
  who: string;
  text: string;
}

// What the run controls need, whether the run is a scripted replay or a real run on the backend.
export interface RunApi {
  mode: "simulated" | "live";
  scenarios: Scenario[];
  scenario: Scenario;
  pick: (id: string) => void;
  view?: RunView;
  log: LogLine[];
  stepTitle?: string;
  statusText?: string; // replaces the status line, for example while connecting or after an error
  idx: number; // -1 before anything has happened
  playing: boolean;
  waiting: boolean; // the run is paused at the approval gate
  finished: boolean;
  speed: number;
  setSpeed: (n: number) => void;
  play: () => void;
  pause: () => void;
  next: () => void;
  decide: (d: "approve" | "reject") => void;
  reset: () => void;
}
