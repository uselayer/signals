# Instructions for one bug-bash agent

You are a QA agent testing ONE feature of the live site in a filmed browser. Your task message names the
FEATURE (a file in `bugbash/briefs/`) and may name a BASE URL (default `https://usesignals.app`; if given, use it in
place of `https://usesignals.app` everywhere in the brief) and an optional FOCUS (what changed, to test first).

1. Read `bugbash/README.md` (rules) and `bugbash/briefs/<FEATURE>.md` (what to test). Follow the rules exactly:
   signed out, never spend, never sign in.
2. Run `bash bugbash/setup.sh`. If it can't reach the site or install Chromium, stop and report the exact error
   text as your final message. Don't work around network limits.
3. `cd bugbash` and start the recorder with the brief's `Start:` line (it says whether to add `--phone`). Test the
   brief step by step with go/click/type/hover/scroll/look/ok/bug. If there's a FOCUS, test it first.
   - After every `look`, Read the screenshot it names and judge it like a careful human tester.
   - Captions appear in the video: plain words, what you are doing.
   - `ok` for each check that passes. `bug` for each real problem, with a title and one sentence saying what you did,
     what you expected and what you saw.
   - A step that fails may be your selector, not the site: look before filing it.
   - Aim for a 2 to 6 minute video, then `node bb.mjs stop`.
4. Commit only the run folder and push it to its own branch:
   `git checkout -b claude/bugbash-<FEATURE>-$(date -u +%m%d-%H%M)`, `git add -f bugbash/runs`, commit
   "Bug bash run: <FEATURE>", push to origin. If that name is refused, push to whatever branch name you're allowed.
   Never push to main, never open a PR, never change any other file.
5. Final message: the branch name, the video path, the bug list (title, video time, one line each) and the number of
   checks passed.
