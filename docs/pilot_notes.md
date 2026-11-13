# Pilot dry run (Nov 13, sprint)

2 tasks (civic_01, health_05) x 12 cells x 1 repeat x 5 arms = 120 calls. File: results/pilot_dryrun.jsonl.

Findings that changed the design:
1. Primacy bias: in repeat 0 both tasks showed P before T, and all arms chose P in nearly every cell,
   including C0 (no credentials). Fix: exact counterbalancing so P precedes T in half of all
   (task, repeat) pairs (25/25 per domain). Each record now stores p_first.
2. command-a-plus-05-2026 with thinking disabled writes its reasoning into the answer text and
   fails to return JSON (16/24 unparseable). The @nothink arm was dropped.

Final arms: command-r7b-12-2024, command-a-03-2025, command-a-reasoning-08-2025, command-a-plus-05-2026@think.
Pilot outputs are not used in the main analysis.
