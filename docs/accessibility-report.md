# Accessibility report (Phase 12)

Target: WCAG 2.2 level AA. Assessment date: 2026-11-16.

## How it was assessed, and the limits of that

* **Code review** of every page and component (about 45 routes) against keyboard and screen-reader behaviour: landmarks, headings, labels, dialogs, focus, live regions, tables, charts, contrast, target size, motion.
* **Automated tests** for dialog keyboard behaviour (`frontend/components/use-modal.test.tsx`) and the existing component tests, which query by role and accessible name.
* **Not done:** testing in a browser with a screen reader (NVDA, JAWS, VoiceOver), keyboard walkthroughs in a real browser, automated scanners (axe, Lighthouse), zoom and reflow checks at 200–400%, and testing with users. Contrast ratios were computed from Tailwind's colour values, not measured on screen.

Because of that, this report can say which defects were found in the code and fixed. It cannot claim the application conforms to WCAG 2.2 AA. A manual screen-reader pass of the workflows listed at the end is the outstanding step.

## Summary

| Severity | Found | Fixed | Open |
|---|---|---|---|
| High (blocks a keyboard or screen-reader user in a core workflow) | 4 | 4 | 0 |
| Medium | 31 | 17 | 14 |
| Low | 21 | 3 | 18 |

## Fixed

### High

| Issue | WCAG | Fix |
|---|---|---|
| The confirmation dialog moved focus back to "Cancel" on every re-render. Typing one character in "Request a revision" or "Reject", or ticking a confirmation checkbox, threw focus out of the field; background polling did the same. This affected publishing, scheduling, approval and AI review. | 2.4.3, 3.2.2 | Focus moves only when the dialog opens. |
| The confirmation dialog did not keep Tab inside it and did not return focus to the control that opened it. | 2.4.3 | Shared `useModal` hook: initial focus, Tab containment, Escape, focus restored on close. |
| The media picker announced itself as a modal dialog but never received focus, had no Escape and no containment. | 2.4.3, 2.1.1 | Uses the same hook. |
| The publishing job details dialog had the same gaps and was unlabelled. | 2.4.3, 4.1.2 | Uses the same hook; labelled by its heading. |

### Medium

| Issue | WCAG | Fix |
|---|---|---|
| No skip link; 14 navigation links precede the content on every page. | 2.4.1 | "Skip to content" link, visible on focus. |
| The page landmark wrapped the header and navigation; navigation unlabelled; current page not indicated. | 1.3.1, 2.4.8 | `<main>` contains only the content; `<nav aria-label="Primary">`; `aria-current="page"` plus a visual state. |
| Every route had the same title, so navigation was silent for screen-reader users. | 2.4.2 | Title per section ("Calendar · Autowok"). Per-page titles within a section are still open. |
| Session check text was outside any landmark and not announced. | 4.1.3 | In `<main>` with `role="status"`. |
| Loading text was not announced. | 4.1.3 | `role="status"` on 34 loading messages. |
| Focus indicator was 2.3:1 against white. | 2.4.7, 1.4.11 | Solid indigo outline, 6.3:1. |
| Workflow choice cards (visually hidden radio buttons) showed no focus indicator. | 2.4.7 | Focus ring on the card. |
| Add-member email field and role select had no label. | 1.3.1, 3.3.2, 4.1.2 | Accessible names added. |
| "Selected platforms" was a label wrapping other labels. | 1.3.1 | `fieldset` and `legend`. |
| Earlier/later radio buttons for an ambiguous time had no group label. | 1.3.1 | Labelled radio group. |
| Password rules were not associated with the password fields. | 1.3.1, 3.3.1 | `aria-describedby`. |
| Research "Run" and "Cancel" gave no feedback and swallowed errors. | 4.1.3, 3.3.1 | Busy state, status message, error alert. |
| Calendar items conveyed status by colour only; platform marks were read as "f" / "IG". | 1.4.1, 1.1.1 | Status in text for screen readers; platform marks named "Facebook" / "Instagram". |
| Calendar day buttons were named only "14"; today marked by colour only; out-of-month dates at 2.4:1. | 2.4.6, 1.4.1, 1.4.3 | Full date as the name, `aria-current="date"`, darker text. |
| Status badges and error text below 4.5:1 (zinc and slate on tinted backgrounds; orange on white). | 1.4.3 | Darker text shades. |
| Chart axis text at 3.6:1; two series colours at 2.8:1 and 2.2:1 against white. | 1.4.3, 1.4.11 | Darker values. |
| Table column headers had no scope. | 1.3.1 | `scope="col"` on 27 headers. |

### Low

Smooth scrolling and transitions now respect `prefers-reduced-motion`. The "+N more" calendar control has a 24-pixel target and names its date. The root error page is announced as an alert and reports the error.

## Not addressed

Listed so they can be scheduled. None blocks a core workflow by itself, but together they are a real cost to screen-reader and keyboard users.

### Medium

| Issue | WCAG | Where |
|---|---|---|
| Titles are per section, not per page; detail pages share their section's title. | 2.4.2 | all detail pages |
| "Add an action" adds on change of a select, so arrow keys on a closed select add the first option. | 3.2.2 | automation form |
| Role and brand selects save on change, then disable or reload, dropping focus. | 3.2.2 | workspace members, social accounts |
| Required action fields are marked only with "*" in the label. | 3.3.2 | automation form |
| Catalogue load failure is plain text without an alert role. | 4.1.3 | automation form |
| Error summaries appear far from the submit button and focus is not moved to them. | 3.3.1 | automation form, content editor, AI workflow form |
| Login and registration errors are announced but not tied to the fields. | 3.3.1 | auth forms |
| Eligibility errors that disable the submit button are not announced. | 4.1.3 | schedule form, publish panel |
| Sync success, upload progress, AI plan preview and workflow completion are not announced. | 4.1.3 | analytics, media, AI workflows |
| Reloading after a save replaces the view with "Loading…", unmounting the focused control. | 2.4.3 | brand sections, workspace, settings pages |
| Step changes and inline edit forms appear without moving focus. | 2.4.3 | brand wizard, brand sections, AI settings, post details |
| Multi-series line charts distinguish series by colour only (a data table alternative exists). | 1.4.1 | analytics charts |
| Several small controls are under 24×24 pixels (carousel dots, reorder arrows, notification actions). | 2.5.8 | post preview, publish panel, automation form, notifications |
| The calendar grid is built from generic elements; weekday headers are not associated with days. | 1.3.1 | calendar |

### Low

Repeated button names without the item's name ("Archive", "Edit", "Remove"); two labels whose accessible name differs from the visible text; tables without captions and metric names not marked as row headers; chart descriptions that read the whole data table; notes exposed only through `title`; a silently ignored seventh comparison selection; a "Steps" toggle without `aria-expanded`; list semantics lost inside an alert; a button nested in a label; an API key field using `autocomplete="new-password"`; an error rendered twice; an unnamed preview video; thumbnail alt text duplicating visible titles; missing level-1 headings while a page loads; an unlabelled navigation and unannounced status on the landing page; the calendar period title changing silently; scrollable regions not focusable in Safari; a queue page that refreshes every 10 seconds without a pause control (2.2.2).

## Checked and found correct

Page language is set. Login and registration fields are labelled with correct `autocomplete` values. Every `outline-none` is paired with a visible focus style. There are no clickable non-interactive elements and no drag-only interactions: media and action reordering use buttons (2.5.7). Status badges always include text. Line charts are keyboard operable with a toggleable data table. Sorting uses labelled selects. View switchers use pressed-state buttons. Decorative images have empty alt text. Error banners use `role="alert"` and success notices `role="status"` on most pages. There are no auto-playing animations.

## Workflows to test manually

With a keyboard only and with at least one screen reader, in this order: sign up and log in; create and switch workspace; add a member; create and edit a brand (all sections); create content, edit a draft, attach media through the picker; submit and approve; upload in the media library; schedule from the calendar and reschedule; publish now and read the job details; read the analytics overview and a chart's data table; build, test and enable an automation; start an AI workflow, review the result, request a revision, accept.
