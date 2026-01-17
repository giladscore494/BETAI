-- Supabase/Postgres schema for automated football match tracker

create extension if not exists "uuid-ossp";

create table if not exists matches (
  id uuid primary key default uuid_generate_v4(),
  league text not null,
  season text,
  home_team text not null,
  away_team text not null,
  venue text,
  kickoff_utc timestamptz not null,
  kickoff_israel timestamptz not null,
  status text default 'scheduled',
  fixture_source text,
  fixture_source_url text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create unique index if not exists idx_matches_unique
  on matches (league, kickoff_utc, home_team, away_team);

create table if not exists predictions (
  id uuid primary key default uuid_generate_v4(),
  match_id uuid references matches(id) on delete cascade,
  model_name text not null default 'gemini-flash',
  model_version text,
  prompt_version text,
  created_at timestamptz default now(),
  duration_ms integer,
  predicted_winner text,
  prob_home numeric,
  prob_draw numeric,
  prob_away numeric,
  recommended_focus text,
  json_payload jsonb,
  sources jsonb,
  data_cutoff_time timestamptz,
  constraint predictions_unique_match unique (match_id)
);

create table if not exists results (
  match_id uuid primary key references matches(id) on delete cascade,
  verified_at timestamptz,
  duration_ms integer,
  final_home_goals integer,
  final_away_goals integer,
  result_text text,
  correct boolean,
  json_payload jsonb,
  sources jsonb,
  data_cutoff_time timestamptz
);

create table if not exists baselines (
  match_id uuid primary key references matches(id) on delete cascade,
  method text,
  prob_home numeric,
  prob_draw numeric,
  prob_away numeric,
  sources jsonb,
  created_at timestamptz default now()
);

create table if not exists runs (
  id uuid primary key default uuid_generate_v4(),
  job_name text,
  started_at timestamptz default now(),
  finished_at timestamptz,
  status text,
  processed_count integer default 0,
  error text,
  notes text
);

create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_matches_updated on matches;
create trigger trg_matches_updated
before update on matches
for each row
execute procedure set_updated_at();
