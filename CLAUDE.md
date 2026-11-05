# How we work on this project

I'm doing a timed coding challenge (about 60 minutes) and will have to explain
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

## Time awareness

Remind me at roughly the 30- and 50-minute marks to check scope. By 50 minutes,
we stop adding features and focus on making the output work and the docs complete.