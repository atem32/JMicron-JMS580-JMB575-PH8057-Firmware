# Final offline validation evidence

`full_suite_summary.json` and `public_suite_summary.json` describe the final canonical source snapshot; their `source_sha256` entries identify every tested code file. PASS applies only to executed checks. Public runs explicitly skip firmware-dependent and private-history checks.

The JSON files here contain sanitized evidence summaries. Relative log names refer to the complete logs under `audit_work/final_full_validation/` or `audit_work/final_public_validation/` in the private archive. They are not missing public test sources. The runner regenerates them locally when the required inputs are supplied.

`historical_labs.json` separates newly replayed available tests, a binary-backed adapter, the preserved original missing-dependency failure, and a recovered historical log whose missing executable tests were not run. `runner_output_alias_before.json` records failures reproduced on disposable files; the final integration log records the corrected regressions.

Earlier audit checkpoints remain in the private archive. Their source hashes and narrower snapshots must not be mistaken for the final run. No hardware command or GitHub publication is represented by these results.
