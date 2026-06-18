"""Just run hfq fetch for 6/17."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.fetch_one_date_eltdx import main

# Patch args to only hfq
import sys
sys.argv = ['fetch_one_date_eltdx.py', '--date=2026-06-17', '--adjust=hfq']
sys.exit(main())
