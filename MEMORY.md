# Master System Directives & Global Development Pipeline Work Rules

> **SERIOUS MANDATORY ORDER:** These rules govern ALL agent sessions, thinking, git workflows, coding, testing, and documentation sync across all projects.

---

## 1. INVERTED DEFAULTS (RUN AUTOMATICALLY IN EVERY SESSION)

1. **Caveman Mode (ON by Default)**:
   - Agent responses to the user MUST be ultra-terse, compressed, and concise by default to minimize token usage (~75% reduction).
   - **CRITICAL**: Caveman mode ONLY affects agent chat responses. Code quality, docstrings, inline code comments, commit messages, PR descriptions, CHANGELOGs, and documentation files MUST remain 100% complete, detailed, and uncompromised.
   - Switch to normal verbose mode ONLY if user explicitly says "talk normally", "explain fully", or "normal mode".

2. **ai-grep (Invisible & Automatic)**:
   - Agent searches codebase silently in the background using grep/ripgrep without asking the user or mentioning `ai-grep`.
   - Never tell the user to run grep or ask permission for searches; fetch code snippets invisibly.

3. **Ponytail Ladder (Lazy Engineering, ON by Default)**:
   - Before writing any non-trivial code, the agent MUST climb the lazy engineering ladder and stop at the first rung that holds:
     1. `YAGNI` (Does this need to exist at all?)
     2. Reuse existing code/pattern in the codebase.
     3. Standard library (`stdlib`).
     4. Native platform/framework feature.
     5. Already-installed dependency.
     6. One-liner implementation.
     7. Minimum correct working code.
   - Never write speculative abstractions or unrequested future-proofing. Mark deliberate shortcuts with `# ponytail: [ceiling & upgrade trigger]` comments.
   - Never skip input validation, error handling that prevents data loss, or security checks at trust boundaries.

4. **Obsidian + Repo Documentation Auto-Sync**:
   - Documentation Agent updates BOTH `~/Documents/Obsidian` and repo `docs/` / `CHANGELOG.md` automatically after every session/task.
   - Keep personal knowledge base (`~/Documents/Obsidian`) and project repo docs in 100% lockstep.

---

## 2. CRITICAL GIT & PR GATE WORKFLOW (MANDATORY FOR ALL CODING TASKS)

- **NEVER push changes directly to `main` branch under ANY circumstances on ANY repository.**
- **Step 1: Branch Checkout**:
  - Always start any coding or feature task by pulling latest `main` and creating a dedicated feature/fix branch:
    `git checkout main && git pull origin main && git checkout -b feature/[TASK_ID]-[description]` (or `fix/...`).
- **Step 2: Auto-Sync Documentation (Post-QA Pass, Pre-Commit)**:
  - Once QA tests pass, BEFORE committing:
    - Update `CHANGELOG.md` with version release notes.
    - Update repo `docs/` specifications.
    - Write a structured checkpoint note to `~/Documents/Obsidian/Projects/[PROJECT]/Checkpoints/` and update `00_Home.md`.
- **Step 3: Commit & Push Branch**:
  - Stage all files (`git add .`), commit (`git commit -m "feat/fix([TASK_ID]): [message]"`), and push the feature branch:
    `git push -u origin feature/[TASK_ID]-[description]`.
- **Step 4: Raise Pull Request via GitHub CLI**:
  - Open PR using `gh pr create --base main --head feature/[TASK_ID]-[description] --title "..." --body "..."`.
  - Provide PR URL to user and request manual review.
- **Step 5: NEVER Merge PR Directly**:
  - **CRITICAL**: The agent is NEVER allowed to merge a PR or push/merge to `main` on its own. ALL PR merges MUST be performed manually by the user on GitHub.
- **Step 6: Merge Verification & Local Cleanup**:
  - Once the user confirms the PR is merged:
    1. `git checkout main && git pull origin main`
    2. Verify merge commits exist: `git log -n 10 --grep="[TASK_ID]"`
    3. Delete LOCAL feature branch only: `git branch -d feature/[TASK_ID]-[description]`.
    4. **DO NOT delete the remote branch on GitHub** (keep for version control reference).
- **Step 7: Post-Merge Obsidian Sync**:
  - Update permanent Obsidian vault notes for the project modules.

---

## 3. DEVELOPMENT PIPELINE MODES & MODEL ASSIGNMENTS

| Mode | When to Use | Workflow & Rules | Model Tier |
|---|---|---|---|
| **Code-First** | Rapid iteration, features <1 day | Describe goal → Ask brief clarifying Qs → TDD failing integration test first → Minimal implementation to pass → Refactor → Debug Agent → QA Agent → Auto-sync docs → Push feature branch & PR. | Fast/Utility Tier (Flash/Haiku) or Pro for complex logic |
| **Design-First** | Complex architecture, systems >2 days | Brief → PM Agent writes Directive (Goal, Acceptance Criteria) → Human approves → Architect Agent writes ADR (Design, Contracts) → **Human approves** → Code Generator implements → Debug → QA → Auto-sync docs → Push feature branch & PR. | **Architect MUST use Advanced Reasoning Tier ONLY** (Pro/Sonnet/o1). Never Fast/Utility Tier. |
| **Research/Brainstorm** | Exploring unknowns, stress-testing | Interview relentlessly (one question at a time with recommended options) → Resolve decision tree → Write research note to Obsidian & repo docs. | Advanced Reasoning Tier (Pro/Sonnet) |

---

## 4. TEST-DRIVEN DEVELOPMENT (TDD) & TESTING RULES

- **Integration-Style Contract Testing**: Write tests targeting public component interfaces.
- **Observable Behavior**: Test *what* the system does (inputs & outputs), not *how* (internal implementation details).
- **NO Mock-Heavy Tests**: Refuse tests that mock internal dependencies, test private methods, or assert on call counts/order.
