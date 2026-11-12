#!/usr/bin/env python3
"""ADK materializes all skill scripts together; copy the fixed helper into task TMPDIR."""
import importlib.util
import json
from pathlib import Path

source = Path(__file__).with_name('swe_edit.py')
spec = importlib.util.spec_from_file_location('fixed_swe_edit', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = module.install(source)
result['usage'] = ('Use run_command: python3 /tmp/swe_edit.py edit PATH with SEARCH/REPLACE blocks on stdin. '
      'Markers: <<<<<<< SEARCH, =======, >>>>>>> REPLACE. SEARCH covers whole lines. '
      'Quoted heredoc: SWE_EDIT_EOF; avoid exact delimiter lines. '
      'Marker collision: --tag E0 and add E0 to each block marker. '
                   'Each edit result lists risk warnings for that edit. create PATH reads stdin exclusively; '
                   'check (optional) lists all changed and untracked files.')
print(json.dumps(result, ensure_ascii=True))
