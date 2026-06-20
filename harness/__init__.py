# Copyright 2026 Haytam Aroui
# SPDX-License-Identifier: GPL-3.0-only
"""be-lexbench — Belgian Legal Evaluation Suite."""

# File-encoding invariant (full rule in harness/run_eval.py module docstring):
# every file open() in the harness MUST specify encoding="utf-8". On Windows,
# locale.getpreferredencoding() is "cp1252" by default and silently corrupts
# FR/NL legal text (État, °, ï, …) otherwise.  If you add a new module that
# reads or writes files, copy this rule at the top of that module too.

JURISDICTION = 'belgium'
