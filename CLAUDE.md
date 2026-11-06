# How we work on this project

I'm doing a timed coding challenge (about 24 hours) and will have to explain
every decision and every line of code to an interview panel afterwards. Your job
is to help me build quickly while I stay in control of the design.

## Workflow (follow this order every time)

1. **Before writing any code**, read the task and the data, then walk me through:
   - what you found (data issues, structure, anything surprising)
   - the key decisions we need to make, with 2–3 options for each and your recommendation
   - any assumptions you'd maake
   Then wait for my answers.
2. **Write or update PLAN.md** with numbered steps and checkboxes. Mark the
   must-haves vs nice-to-haves, so we know what to cut if time runs short.
3. **Build one step at a time.** After each step, stop and tell me:
   - what you did, in plain English
   - row counts before and after (for any data change)
   - anything you weren't sure about
   Don't start the next step until I say go.
4. **Ask before deciding.** If you hit a decision or assumption that affects the
   results (dropping rows, filling missing values, scoring weights, matching rules),
   ask me first. Batch several questions together when you can, to save time.
5. **Always update the design docs** after every step, before moving on.

## Design docs (keep them short, write them in first person as me)

- **PLAN.md:** steps with checkboxes; update status as we go.
- **ARCHITECTURE.md:** inputs → scripts → outputs, with a short text diagram.
- **DECISIONS.md:** each decision or assumption, the options considered, why I
  chose this one, and how many rows it affected. Note who decided ("I chose…").
- **README.md:** written at the end; covers what it does, how to run it, how to use the output.

## Code rules

- Keep code simple and readable. Prefer plain pandas over clever tricks; I must
  be able to explain every line.
- Never modify the original input files; work on copies.
- Put tunable numbers (weights, thresholds) in one config block at the top.
- Keep API keys in environment variables. Handle auth errors, rate limits (429),
  and pagination for any API.
- Check for junk rows: blank rows, duplicates, and test or placeholder accounts
  (names or emails containing "test", "demo", "do not contact").
- Ask before adding any new library.

## Boundaries

- **Never read `.env`** in any form, not even variable names. If you need to know
  whether a variable is set, ask me.
- **Don't access anything outside this project folder** (Desktop, Downloads, other
  folders) without asking me first. If a file I mention isn't in the project, tell
  me and ask.
- **Throwaway scripts go in `scratch/`** inside the project (git-ignored), not in
  system temp folders.

## Time awareness

This is a ~24-hour take-home. Remind me to check scope at each checkpoint:

| By about | Done |
| --- | --- |
| 8h | Task 1 parser (steps 1–11 in PLAN.md, including headings and tests) |
| 10h | Task 2 database: schema, loader, sample queries |
| 13h | Task 3 duplicate detection + `duplicates_report.csv` |
| 15h | Task 4 notifications: draft replies + live MCP send |
| 15h+ | Docs and polish: README.md, AI_USAGE.md, final checks |

**Re-plan (at about hour 14, ~10 h left):** DB by hour 16 · dedup by hour 19 · notifications by hour 21 · docs and final checks by hour 24. Nice-to-haves only once Task 4 works end to end.

If a checkpoint slips, we stop adding features to that task and make its output
work and its docs complete before moving on.