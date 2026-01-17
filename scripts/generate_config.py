#!/usr/bin/env python3
"""
Generate web/config.js from environment variables without printing secrets.
Intended for Cloudflare Pages build step.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
  supabase_url = os.environ.get("SUPABASE_URL")
  supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY")

  if not supabase_url or not supabase_anon_key:
    sys.stderr.write("Missing SUPABASE_URL or SUPABASE_ANON_KEY; not writing web/config.js\n")
    return 1

  config_path = Path(__file__).resolve().parent.parent / "web" / "config.js"
  config_path.write_text(
      f"window.SUPABASE_URL = {json.dumps(supabase_url)};\n"
      f"window.SUPABASE_ANON_KEY = {json.dumps(supabase_anon_key)};\n",
      encoding="utf-8",
  )
  print("config.js generated.")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
