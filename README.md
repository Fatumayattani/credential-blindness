# Credential Blindness

Do LLM agents trust content credentials (C2PA) that fail verification?

Submission to the Apart Research AI x Epistemics Research Sprint, Nov 13-15, 2026 (Track 2: Trust Infrastructure).

## Pre-sprint disclosure
Work done before Nov 13, 2026 (all files marked `PRE-SPRINT`):
- Environment setup and c2patool / C2PA SDK tooling checks
- Harness code: certificate generation, source builder, prompt builder, runner, scorer
- One example task (`data/tasks/example_task.json`) used only for pipeline testing; excluded from the study
- 10 live API calls on the example task to check plumbing (JSON parsing, token usage, thinking on/off).
  Outputs were deleted and never scored or analysed.

No study tasks, experimental runs, or results were produced before the sprint.

## Acknowledgements
Compute provided by a Cohere Labs Catalyst Grant.
