CREATE TABLE videos (
  id TEXT PRIMARY KEY,
  file_name TEXT NOT NULL,
  duration_seconds REAL,
  mime_type TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE analysis_runs (
  id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL REFERENCES videos(id),
  min_highlight_duration REAL NOT NULL,
  sensitivity REAL NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE highlight_candidates (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES analysis_runs(id),
  start_seconds REAL NOT NULL,
  end_seconds REAL NOT NULL,
  score REAL NOT NULL,
  visual_score REAL,
  audio_score REAL,
  language_score REAL,
  continuity_score REAL,
  explanation TEXT
);

CREATE TABLE exports (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES analysis_runs(id),
  candidate_id TEXT REFERENCES highlight_candidates(id),
  path TEXT NOT NULL,
  format TEXT NOT NULL,
  created_at TEXT NOT NULL
);
