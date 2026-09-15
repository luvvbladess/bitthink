---
target: chat
total_score: 17
p0_count: 2
p1_count: 2
timestamp: 2026-07-10T23-25-16Z
slug: frontend-src-pages-chatpage-tsx
---
Method: dual-agent (A: design-review-retry · B: detector-evidence)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 1 | `wsStatus` (connecting/closed/error) has no dedicated UI — only silently disables `MessageInput` (ChatPage.tsx:218); loading vs. empty state indistinguishable. |
| 2 | Match System / Real World | 2 | Header buttons read literal "IMG"/"DOCX" (ChatPage.tsx:208-213) — file-extension jargon, not real-world verbs. |
| 3 | User Control and Freedom | 2 | Delete conversation (ChatSidebar.tsx:113) fires instantly, no confirm/undo. Rename has clean Escape-to-cancel. |
| 4 | Consistency and Standards | 2 | `IconButton` misused as text-button for IMG/DOCX; box-shadow values drift from documented tokens in 2 places. |
| 5 | Error Prevention | 1 | No confirmation on destructive delete; dead `Microphone` button (MessageInput.tsx:71) with no onClick at all. |
| 6 | Recognition Rather Than Recall | 2 | Rename/delete icons only appear on `:hover` (ChatSidebar.tsx:109) — recall-dependent, unreachable on touch. |
| 7 | Flexibility and Efficiency | 2 | Enter/Shift+Enter works well; no message editing, no shortcuts surfaced, no bulk actions. |
| 8 | Aesthetic and Minimalist Design | 3 | Genuinely restrained, one accent, no clutter; minor deduction for shadow/blur inconsistency. |
| 9 | Error Recovery | 1 | WS/upload errors appended as plain chat bubbles with "Ошибка:" prefix, same visual weight as real content, no retry. `exportDocx` has no try/catch at all. |
| 10 | Help and Documentation | 1 | No tooltips on any icon-only control (8 confirmed instances), no empty-state guidance in sidebar. |
| **Total** | | **17/40** | **Poor — major UX work needed before this feels shippable to paying users** |

## Anti-Patterns Verdict

**LLM assessment**: Not templated in the generic-SaaS sense — no hero-metric, no gradient text, no bento grid, no uppercase eyebrows. The `ThinkingIndicator` orbiting-dot component and blur-fade message entrance are genuine bespoke touches. But the surface leaks its own stated rules: hard `box-shadow` values stacked under `backdrop-filter` blur contradict DESIGN.md's "Blur-Not-Shadow Rule."

**Deterministic scan** (`detect.mjs --json` on `ChatPage.tsx` + `features/chat/`, exit code 2, 5 files scanned):
- `design-system-font` warning: `ChatMessage.tsx:43` uses `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace` for `<code>` blocks — not declared in DESIGN.md's typography (which names only Inter Variable). **Likely false positive** — a monospace stack for code rendering is standard convention, not slop — but technically undocumented; worth a one-line addition to DESIGN.md rather than a design fix.
- Grep evidence confirms the shadow drift the LLM review flagged: `ChatMessage.tsx:32` (`0 4px 24px rgba(0,0,0,0.12)`) matches neither the documented `glass-ambient` nor `accent-glow` token — a real, in-scope deviation.
- Grep evidence **quantifies** the LLM review's accessibility concern precisely: **8 icon-only `IconButton`s with no `aria-label`** across the chat surface — `ChatSidebar.tsx:87,90,110,113`, `MessageInput.tsx:49,71,74-86`, `ChatPage.tsx:198`. This is the single most concrete, fixable finding in the whole report.
- No `border-left`/gradient-text/side-stripe violations found anywhere in scope — clean on the absolute bans.
- One discrepancy between assessments: the LLM review named hardcoded `#111` in `ModelSelector.tsx`/`ImageGenerationDialog.tsx` as an off-token color; the detector's hex grep (targeting the 6-digit palette values) found none — likely because its pattern didn't match 3-digit hex shorthand (`#111`). Treating the LLM's finding as real; the detector's regex has a blind spot here, not a false alarm.

**Browser visualization**: unavailable — no browser automation tool exposed in this session. No visual overlay was shown; this critique rests on source review and static analysis only.

## Overall Impression

The chat surface is visually disciplined and avoids the crop of generic-AI tells (no gradient text, no hero clichés, no bento grids) — the biggest brand risk from PRODUCT.md is not present. But it is failing its own stated audience: non-technical paying users. The single biggest opportunity is closing the "silent failure" gap — a WebSocket drop or an unlabeled icon button both currently fail invisibly, and for a small paying user base that experience reads as "the app is broken," not "the network hiccuped."

## What's Working

- **`ThinkingIndicator.tsx`** — a genuinely bespoke orbiting-dot animation with contextual status copy ("Обрабатываю {file}...") — the strongest reassurance moment in the whole flow.
- **`MessageInput.tsx`** — Enter/Shift+Enter handling and disabled-state gating (`!text.trim() || disabled`) is correctly implemented.
- **`ModelSelector.tsx:78`** — locked/unavailable models shown with a `Lock` icon and reduced opacity, a clean tiered-plan affordance that matches the "premium through restraint" principle.

## Priority Issues

- **[P0] Silent connection failures**: `wsStatus !== 'open'` only disables the input (ChatPage.tsx:218); `useWebSocket.ts` has no reconnect logic. **Why it matters**: a paying non-technical user sees a dead input with zero explanation — reads as a broken app. **Fix**: add a visible connection-status banner/pill for non-open states, plus auto-reconnect with backoff. **Suggested command**: `/impeccable harden`

- **[P0] Irreversible instant delete**: Conversation delete (ChatSidebar.tsx:113) fires on a single click, no confirmation or undo. **Why it matters**: permanent data loss from one mis-tap, worse on mobile where the target is small. **Fix**: confirm dialog or undo-toast before permanent delete. **Suggested command**: `/impeccable harden`

- **[P1] 8 icon-only controls with no accessible name**: `ChatSidebar.tsx:87,90,110,113`, `MessageInput.tsx:49,71,74-86`, `ChatPage.tsx:198` — confirmed by both source review and detector grep. **Why it matters**: screen readers announce these as unnamed buttons; violates the WCAG AA baseline PRODUCT.md committed to. **Fix**: add `aria-label` to every icon-only `IconButton`, plus a visible tooltip for sighted mouse users. **Suggested command**: `/impeccable audit`

- **[P1] Jargon labels for non-technical users**: header actions render literal "IMG"/"DOCX" text inside `IconButton`s (ChatPage.tsx:208-213), no tooltip. **Why it matters**: fails Match-Real-World and Recognition-not-Recall for the stated non-technical paying audience; contradicts PRODUCT.md's "clear and beautiful interface" priority. **Fix**: icon + short real-word label ("Изображение", "Экспорт"). **Suggested command**: `/impeccable clarify`

- **[P2] Hover-only rename/delete affordances**: `ChatSidebar.tsx:109` reveals icons only on parent `:hover`, no `:focus-within` equivalent. **Why it matters**: entirely undiscoverable on touch (mobile Drawer) and for keyboard-only users. **Fix**: always-visible reduced-opacity icons at the mobile breakpoint, add `:focus-within` reveal for keyboard nav. **Suggested command**: `/impeccable adapt`

## Persona Red Flags

**Jordan (first-timer)**: IMG/DOCX abbreviations assume file-format literacy; a WS disconnect gives zero explanation — Jordan will likely conclude the app crashed rather than that the connection dropped.

**Sam (accessibility)**: all 8 confirmed icon-only buttons (Paperclip, Microphone, PaperPlaneRight, Trash, PencilSimple, CaretDown, hamburger) carry no `aria-label`; a screen reader announces unnamed buttons throughout the primary chat flow. The disabled-input state during connection trouble has no `aria-live` announcement either.

**Casey (mobile)**: rename/delete controls are functionally unreachable on touch (hover-only reveal in the Drawer sidebar); icon hit targets (`size="small"` IconButtons with 14-16px glyphs) sit well under the ~44px touch-target guideline.

## Minor Observations

- Hardcoded `#111` in `ModelSelector.tsx:51` and `ImageGenerationDialog.tsx:51` instead of the theme's `surface.elevated` token.
- `exportDocx` (ChatPage.tsx:156-171) has no loading indicator and no try/catch — a failed export fails completely silently.
- Errors are appended as normal-styled assistant chat bubbles, visually indistinguishable from real answers, with no retry affordance.
- Sidebar has no explicit "no conversations yet" empty state — a zero-length array just renders a blank area.
- `Microphone` button in `MessageInput.tsx:71-73` has no `onClick` at all — a fully dead affordance that promises a feature which does nothing.
- `ChatMessage.tsx:43`'s monospace code-block font is undeclared in DESIGN.md — worth adding one line to the typography section rather than treating as a defect.

## Questions to Consider

- If the WebSocket drops mid-stream, the partial reply lives only in a ref (`pendingContentRef`) with no flush/recovery path — does the user just lose an in-progress answer with no way to know it happened?
- Was the hover-gated rename/delete pattern ever checked against the mobile Drawer breakpoint, or only ever viewed on desktop?
- "IMG"/"DOCX" read as internal engineering shorthand rather than the "premium, calm, ethereal" voice PRODUCT.md asks for — was this copy ever shown to a non-technical user, or did it ship as a placeholder?
