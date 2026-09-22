# Frontend guide: customizing Syncope's look

## 1. Overview

This is the reference for changing how the app *looks* - colors, fonts, buttons, spacing,
nav branding - without touching Python code. There's no build step: one CSS file
(`syncope/static/syncope/style.css`), self-hosted fonts, and Django templates. Edit,
save, reload the page.

The whole restyle is built around one idea: **almost every visual decision lives in a
handful of CSS custom properties (design tokens) at the top of `style.css`.** If you want
to reskin the app for your own group - different palette, different fonts, different
button shape - you should be able to do it by editing that one `:root` block and nothing
else. Sections below tell you exactly where to look for anything not covered by tokens
alone (mainly: swapping the fonts themselves, and the sidebar logo).

> Status: this guide is being written alongside the CSS overhaul itself (2026-09-11),
> section by section as each part of the app is restyled. Sections not yet filled in
> are marked below.

## 2. Design tokens

Everything here lives in the `:root { ... }` block at the top of
`syncope/static/syncope/style.css`. Change a value, save, reload - every place that uses
it updates.

| Token | Default | Used for |
|---|---|---|
| `--color-bg` | `#f4f1ea` | Page background |
| `--color-bg-subtle` | `#ebe6d9` | Secondary/alt section backgrounds |
| `--color-surface` | `#ffffff` | Card/panel/table background |
| `--color-border` | `#e5dfd6` | Default borders (cards, tables, inputs) |
| `--color-border-subtle` | `#efe9dd` | Lighter dividers |
| `--color-text` | `#2c2a28` | Body text |
| `--color-text-muted` | `#5c574f` | Secondary/helper text |
| `--color-text-on-accent` | `#ffffff` | Text on filled buttons/badges |
| `--color-primary` | `#8b6f47` | Brand accent - primary buttons, links |
| `--color-primary-hover` | `#a8895e` | Hover state for the above |
| `--color-danger` | `#c0392b` | Destructive actions (delete buttons) |
| `--color-danger-hover` | `#a3301f` | Hover state for the above |
| `--color-success-bg` / `-border` / `-text` | greens | Success flash messages |
| `--color-error-bg` / `-border` / `-text` | reds | Error flash messages |
| `--color-warning-bg` / `-border` / `-text` | ambers | Warning flash messages |
| `--color-info-bg` / `-border` / `-text` | blues | Info flash messages |
| `--color-attendance-0`…`-4` | see comment above them | Attendance chip colors, keyed by `AttendanceType` pk (0=TBD, 1=Present, 2=Work/School, 3=Illness, 4=Private/Vacation) - **don't reorder these**, the pk mapping is load-bearing |
| `--font-heading` / `--font-body` | see Fonts section | Typography |
| `--font-size-2xs` / `-xs` / `-sm` / `-md` / `-xl` | 0.75rem / 0.8rem / 0.85rem / 0.9rem / 1.5rem | Text sizing scale |
| `--space-1`…`-6` | 4px → 32px | Spacing scale used for padding/margin/gap throughout |
| `--radius-sm` / `-md` | 6px / 10px | Corner rounding (buttons/inputs use `sm`, cards/tables use `md`) |
| `--shadow-sm` / `-md` | subtle box-shadows | Card and hover elevation |
| `--transition-fast` | `0.2s ease` (`0s` when `prefers-reduced-motion: reduce`) | All hover/transition timing |
| `--sidebar-width` | `250px` | Sidebar column width in `.grid-container` |

**Recipe - change the whole color scheme:** edit the `--color-*` values. Every button,
alert, card, and table border is built from these, so a new palette propagates
everywhere automatically. Re-check contrast if you change `--color-primary` or
`--color-text-muted` against `--color-bg`/`--color-surface` - see the note on WCAG AA
below.

**Contrast note:** the shipped palette was picked so every text/background pairing hits
at least 4.5:1 contrast (WCAG AA for normal text), including button-label-on-fill and
muted/link text on both the page and card backgrounds. If you swap `--color-primary` or
the neutral colors, re-check the pairing you changed - a quick way is to plug the two hex
values into any online WCAG contrast checker.

## 3. Fonts

Self-hosted, no external font CDN (keeps the app free of a third-party network
dependency). Two variable-weight `.woff2` files live in
`syncope/static/syncope/fonts/`:

- `eb-garamond-latin.woff2` - heading font (`--font-heading`), a serif
- `inter-latin.woff2` - body font (`--font-body`), a sans-serif

Both are declared via `@font-face` right above the `:root` block in `style.css`, with
`font-display: swap` so text isn't invisible while the font loads. Each file is a
variable font covering weights 400-500 in the Latin subset only (this app doesn't need
Cyrillic/Greek/etc. glyphs, so those subsets were skipped to keep the files small).

**Recipe - swap to a different font pairing:**
1. Get `.woff2` file(s) for your chosen font(s) and drop them in
   `syncope/static/syncope/fonts/`.
2. Update the `@font-face` `src` path(s) and `font-family` name(s) at the top of
   `style.css`.
3. Point `--font-heading` / `--font-body` at the new family name(s).

No template changes needed - every heading and body element already references the
tokens, not a hardcoded font name.

## 4. Cascade layers

`style.css` is organized into five `@layer`s, declared once near the top:

```css
@layer reset, base, layout, components, utilities;
```

In priority order (later wins ties regardless of selector specificity): `reset` → `base` → `layout` → `components` → `utilities`. `@font-face` and the `:root` token block stay **unlayered**, above the `@layer` statement, so custom properties remain available everywhere.

| Layer | Holds |
|---|---|
| `reset` | `*` box-sizing, `body` margin reset |
| `base` | `body`/heading/link typography defaults, the generic `:focus-visible` outline for native form elements |
| `layout` | Sidebar, `.grid-container`, nav/org list, `.main-content`/`.footer`, mobile topbar/drawer shell |
| `components` | Buttons, forms, cards, alerts, breadcrumbs, save-bar, section headers, and the entire **Tables** system (below) |
| `utilities` | `.visually-hidden`, `.inline-form`, `.col-num`, `.sticky-col`, `.att-type-0..4`, `.table-container`, `.sortable-header`, `.empty-state`, responsive touch-target/label-swap helpers |

**Why this matters if you add a rule:** a rule in `@layer utilities` always beats a same-element rule in `@layer components`, no matter how specific the components-layer selector is - layer order is checked before specificity. If you need one rule to override another for the *same CSS property* on the same element, put both in the same layer and let normal specificity/source-order decide (see the comment above `.table-cell-attendance-disabled` in `style.css` for a worked example). Most of the file was moved into layers with its existing selectors unchanged - only the Tables section below got a full rewrite.

## 5. Component classes

Defined in `style.css` under clearly labeled `/* --- Section --- */` comments inside `@layer components`:

| Class | Lives under (`style.css` comment) | Use |
|---|---|---|
| `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-link`, `.btn-remove` | `/* --- Buttons --- */` | Every button/button-styled link in the app - one shared height and font, color-only modifiers. All are solid-filled (`.btn-secondary`/`.btn-danger` used to render with a transparent background - now a solid one matching the surface they sit on, e.g. `--color-bg` on the page, `--color-ink` on the dark sidebar) - no ghost/see-through buttons anywhere. `.btn-remove` is the compact inline `×` used on table/formset rows, background-less by design (not a page-level action). Button text itself is pinned to `14px`/`20px` (not the `--font-size-md` rem token) so its rendered height is a clean pixel value instead of a sub-pixel one. |
| `.form-actions` | same section, right after `.btn-link` | Wraps a form's submit/cancel row - see **Forms** below for the layout rule |
| `.form-group`, `.form-label`, `.form-help`, `ul.errorlist` styling | `/* --- Forms --- */` | Field wrapper + label + help text + Django's built-in error list |
| `.card`, `.card-grid` | `/* --- Cards --- */` | Used by `home.html`'s membership cards, `org_dashboard.html`'s quick-links, and `import_hub.html`'s step cards - all three share the same shape: `<h3>` title + `<p>` description + a `.btn-secondary` link as the last child |
| `.table`, `.table-detail`, `.table-grouped`, `.totals-row`, `.table-narrow`, `.empty-state` | `/* --- Tables --- */` | List/detail data tables - see **Tables** below |
| `.table-matrix`, `.table-event-col`, `.table-event-header(-strong)`, `.table-cell-attendance`, `.table-row-total`, `.table-comment(-input)` | same section | The attendance/pivot grid variant - see **Tables** below |
| `.alert`, `.alert-success/-error/-warning/-info` | defined earlier, alongside `.messages` (Phase 2) | Flash messages - `class="alert alert-{{ message.tags }}"` |

**Recipe - change what a button looks like everywhere:** edit `.btn` (shared shape/spacing/font) or one of `.btn-primary`/`.btn-secondary`/`.btn-danger`/`.btn-link` (color only). Every button in the app uses these - there's no template with its own one-off button CSS left in the areas this pass covered.

**Naming convention:** every component class uses plain dash-modifiers (`.btn-primary`, `.table-detail`, `.table-matrix`) - there is no BEM (`__`/`--`) anywhere in `style.css` any more. The matrix-table/badge/share-result classes used to be the one BEM pocket in the file (`.table--matrix`, `.table__event-col`, `.badge--primary`, `.share-result--floating`, etc.) and have been renamed to the same dash convention as everything else (`.table-matrix`, `.table-event-col`, `.badge-primary`, `.share-result-floating`). Keep new classes dash-named too.

## 6. Tables

All data tables share one component: `class="table"` on the `<table>` element, styled with CSS nesting (`.table { & thead th { ... } & tbody td { ... } ... }`) and a `@container` query on the sticky header/cell padding - compact by default (mobile-first), roomier once the table's `.table-container` wrapper (which declares `container-type: inline-size`) has at least `36rem` to work with. This replaced the old page-level `max-width: 768px` override that touched bare `th`/`td` selectors.

**Modifiers (used with `.table`, unchanged names from before this pass):**
- `.table-detail` - key/value definition table (see `song_detail.html`, `org_member_detail.html`, `invitation_detail.html`)
- `.table-grouped` (+ a `group-start` class on the first `<tr>` of each group) - draws a divider between groups
- `.totals-row` (on a `<tr>`) - bold divider row for a running total
- `.table-narrow` - caps the table's width (`poll_person.html`)
- `.empty-state` (on a `<p>`, not a table modifier) - centered muted text for "nothing here yet" messages

**`.table-matrix` - attendance/pivot grids:** one shared definition for the three attendance grids (`poll_detail.html`'s votes summary, `poll_attendance.html`'s single-person editor, `attendance_dashboard.html`'s full matrix), replacing what used to be three separate, diverging page-local `<style>` blocks with different pixel values for the same concept. Add `.table-matrix` alongside `.table` (and `.table-grouped` where rows are grouped). Elements:
- `.table-event-col` on a `<th>`/`<td>` - fixed-width event column (`--table-matrix-col-w`)
- `.table-event-header` wrapping a rotated date/label inside a `<th>` (rotate(-90deg), matches `syncope-compare`'s attendance dashboard look); add `-strong` for non-regular event types
- `.table-cell-attendance` on the clickable/status chip (`--table-matrix-cell-size`); add `-disabled` for a non-interactive/grayed cell, or `-static` for a page where nothing is clickable at all (`poll_detail.html`)
- `.table-event-col-ineligible` for an empty, non-interactive cell
- `.table-row-total` on a totals `<tr>` (the matrix-specific equivalent of `.totals-row`)
- `.table-comment` (read-only) / `.table-comment-input` (editable) for the small note under/in a cell
- `.legend` wraps the small "legend" of example chips above a matrix table - `.table-cell-attendance` inside `.legend` auto-sizes and drops the hover/pointer affordance

The attendance status colors themselves (`.att-type-0`…`-4`) are unchanged - see the `--color-attendance-*` token row above. Matrix table headers capitalize the same way every other `.table` header does (`text-transform: uppercase`) - there is no longer a matrix-specific exception.

**Row-number columns:** the leading `.col-num` header is left blank (no `#` text) app-wide - the row number/count still renders in the body cell below it, the header itself just doesn't repeat it. The one exception is a genuinely sortable ID column (e.g. `song_list_results.html`'s Song ID), which keeps its `ID` label and sort arrow since it's a real sortable field, not a row counter.

**Not migrated in this pass:** the ~16 other list-table templates (song/person/event/project/poll/invitation lists and detail sub-tables) keep using `.table`/`.table-container`/`.sticky-col`/`.col-num`/`.sortable-header` exactly as before - no changes needed there, since none of those class names changed.

**Button hierarchy rule (apply this, don't reinvent per page):** one `.btn-primary` per screen (the actual commit action - Save/Update/Send/etc.), everything secondary/navigational is `.btn-link` (plain, e.g. Cancel) or `.btn-secondary` (outlined, e.g. an alternate "Return to X" action), and `.btn-danger` is reserved for destructive actions only, kept on its own confirm-delete page or behind an existing `confirm()` dialog - never placed next to a primary Save button in the same `.form-actions` row.

## 7. Utility classes

- **`.inline-form`** - replaces `style="display:inline"` on the small one-button forms scattered through detail/list pages (delete/unlink forms sitting inline with links). Purely `display: inline`.
- **`.visually-hidden`** - a hard `display: none`, *not* the accessible-but-present clip technique some codebases use under this name. Only ever put it on wrapper `<div>`s that hold nothing but a CSRF token - there's no content to keep available to assistive tech there, so the stronger hide is fine and matches what those wrappers already did via inline `style`.
- **Generic `input[type="checkbox"]`/`input[type="radio"]`** spacing (not a class, an element selector) - covers Django's default `CheckboxSelectMultiple`/`RadioSelect` output (skills/roles, attendance type) without a custom widget template. Slightly less polished alignment than a bespoke layout would give; a real widget-template override is the natural next step if this needs more polish later.
- **`.form-error`** - plain `color: var(--color-error-text)`, for the couple of hand-rolled error messages that were previously inline `style="color:red"` (formset non-field errors).

## 8. Forms

**The pattern:** `{% for field in form %}` + a `.form-group` wrapper, using `{{ field.errors }}` directly (Django already renders that as `<ul class="errorlist">`, which `.form-group` already styles - don't hand-loop `field.errors` yourself). See `song_form.html` and `event_meta_edit.html` for the full pattern, including how `song_form.html` branches on `field.name` to insert its "+" add-related-person buttons inline without breaking the loop. Plain `{{ form.as_p }}` forms (e.g. `event_form.html`, `signup.html`, `login.html`) needed no template changes at all - `style.css` styles Django's default `<p>`/`<label>`/`.errorlist`/`.helptext` output directly via `form p ...` selectors, so `.form-group` and `as_p` both render consistently without picking one convention app-wide.

**Resource formsets:** `person_form.html`, `org_member_form.html`, `event_meta_edit.html`, and `song_form.html` each embed a `Resource` formset (a URL + description a person/member/event/song links out to). All four share the same shape now: an `<h3>Resources</h3>` heading *outside* the `{% for r_form in resource_formset %}` loop (it used to render once per row on `song_form.html` - a copy-paste bug), each row wrapped in `<div class="resource-row">`, and - for an existing row - a delete checkbox with the same `onclick="return confirm('Delete this resource? Remember to press save.');"` guard and the same `<small class="form-help">Delete this resource</small>` label everywhere (`event_meta_edit.html`'s row also needs its `#resource-formset`/`#resource-rows`/`.resource-row` markup intact, since its JS clones the last row to add a blank one - the checkbox/label addition doesn't touch that).

**Button row convention - `.form-actions`:** always a single `<div class="form-actions">` containing, in this DOM order: Cancel/Back link (`.btn-link`) → optional secondary link (`.btn-secondary`, e.g. a "Return to X" navigation) → the primary submit button (`.btn-primary`) last. Flexbox (`justify-content: flex-end`) renders that as cancel-left/primary-right on desktop, clustered to the right edge; on the existing 768px breakpoint `justify-content` switches to `space-between` so the same cancel-left/primary-right order spreads across the full width instead. This is deliberately the modern web convention (secondary-left/primary-right, e.g. Bootstrap/Material), not the older Windows-dialog "primary-left" pattern.

**Delete button placement:** a page-level `.btn-danger` "Delete" for the record being edited lives only on that record's own edit page (never on its detail/dashboard/list view), and sits in its own `<p>` placed *after* (below) the `.form-actions` row - the opposite side of the screen from the primary Save button, since `.form-actions` clusters right while a bare `<p>` sits left. See `org_form.html`/`event_meta_edit.html` for the pattern.

**Button labels are single words, app-wide** - not just inside `.form-group`/`.form-actions`. "Save", "Cancel", "Delete", "Update", "New", "Add", "Send", "Signup", "Unlink" etc. Where a one-word label alone would be ambiguous (e.g. multiple "New" buttons on one page), the disambiguating context goes in a nearby heading or a `title="..."` tooltip instead of stretching the button text - see the composer/arranger/poet/translator "+" buttons in `song_form.html`, or the "New"/"Clear" search buttons in `event_songs_edit.html`/`event_attendance_edit.html`, both of which carry a `title` attribute. Plain in-page navigation links (not buttons) - e.g. "Sign up form" on the login page - are outside this rule; it only applies to actual buttons/button-styled actions.

A "return to X" navigation action (`return_url`/`return_label` in the view context) is always a plain `<a class="btn btn-secondary">`, never a `<button onclick="window.location.href=...">` - that JS was pure navigation with nothing else attached, so the link does the same job with less code. Anywhere a button still uses `onclick`/JS in this app, it's because it genuinely does something beyond navigation (a `confirm()` guard, a formset row action, the save-bar's dirty-state tracking) - don't collapse those to links.

## 9. Navigation & branding

The sidebar (`syncope/templates/syncope/base.html`) is one `<nav class="sidebar">` with
four parts, top to bottom:

- `.sidebar-header` - now an `<a href="{% url 'syncope:home' %}">` wrapping the logo (`<img class="sidebar-logo">`) + `.sidebar-brand` wordmark, so clicking either takes you home
- `.sidebar-user` - the logged-in username
- `.menu-links` - the nav list: Home / Update profile / Invitations, then a **Private** section (`.section-label` "Private") with Archive (your own songs, reuses `song_list` with your own username) and Contacts (your own roster, reuses `org_member_list` with your own username - `AccessControl.get_org_roles` already grants a user ADMIN-level access to their own username's roster, so no backend changes were needed), then an **Orgs** section (`.section-label` "Orgs", was "Groups") with the nested `.org-list`/`.org-submenu` per organization. Each `.org-item` shows just the org name now - no active-state dot and no per-membership "name · roles" line (both removed for a cleaner list).
- `.sidebar-footer` - Logout (or Sign Up/Login when logged out)

**Recipe - change the logo:** replace
`syncope/static/syncope/images/sitelogo.png` with your own image (any size - it's
displayed at a fixed 48px via `.sidebar-logo` in `style.css`), or point the `<img src>`
at a different static path.

**Recipe - change the brand name/wordmark:** edit the text inside `<p
class="sidebar-brand">` in `base.html`.

**Recipe - add a new nav item:** copy an existing `<li><a href="...">` line and give it
its own `url_in` check so it highlights when active, e.g.:

```html
<li><a href="{% url 'syncope:my_view' org.user.username %}"
   {% if url_username == org.user.username and request.resolver_match.url_name|url_in:'my_view,my_view_detail' %}class="active"{% endif %}>
   My Feature
</a></li>
```

`url_in` (from `{% load url_tags %}`, already loaded at the top of the sidebar) takes a
comma-separated list of URL names and returns true if the current page's URL name is one
of them - that's what drives the `.active` highlight class. `url_username` is set by
`syncope/middleware.py` from the URL's `username` path segment, so multi-org users only
see the active state on the org they're currently viewing.

**Page-level headings:** every page's first `<h1>` sits at the same vertical position now
(`.main-content h1:first-of-type { margin-block-start: 0 }`) regardless of whether it's a
bare `<h1>` (which used to keep the browser's default top margin) or one wrapped in
`.section-header` (which already zeroed it via `.section-header h1 { margin: 0 }`) -
previously these two cases sat at different heights purely by accident of markup. Any
page whose `<h1>` has an adjacent "Edit" (or similar) button should wrap both in
`.section-header` rather than stacking the button in a separate `<p>` below the heading -
`.section-header`'s `align-items: center` keeps the button vertically centered against the
heading on the same row; see `event_detail.html`, `song_detail.html`,
`org_member_detail.html`, `project_detail.html`, `poll_detail.html`, `song_quotes.html`,
`org_dashboard.html` for the pattern.

Invitations badges (`.nav-badge`) use the same pattern: the count comes from
`pending_invitations` (personal) or `membership.pending_invitations` (per-org), both
already computed in the view context - only shown when non-zero.

## 10. Responsive behavior

Two mechanisms, no separate mobile stylesheet or JS-based breakpoint detection:

- **`@media (max-width: 768px)`** - there are now several of these (one per `@layer`
  section that needs a mobile override - layout/sidebar, forms, the filter panel, touch
  targets in utilities - search for `768px` to find them all), instead of one giant block,
  so each override sits next to the rule it's overriding. Below 769px:
  - The sidebar becomes a fixed, off-canvas drawer (`transform: translateX(-100%)`),
    toggled by `.grid-container.menu-visible` - driven by the `toggleMenu()` function in
    `base.html`, unchanged by this pass.
  - `.form-actions` switches from clustering right (`justify-content: flex-end`) to
    spreading full-width (`justify-content: space-between`) - cancel stays pinned to the
    left edge, primary to the right, same as desktop, just spread out instead of clustered.
  - Text inputs and `.btn` (all button variants) get a `min-height: 44px` touch target.
  - The save-bar becomes `position: fixed` to the viewport bottom.
- **`@container` on `.table`** - tables no longer use the page breakpoint at all. Their
  wrapper (`.table-container`) declares `container-type: inline-size`, and `.table` itself
  is compact by default with a `@container (min-inline-size: 36rem)` query making cell
  padding/font-size roomier once the table's own box (not the viewport) has the space -
  see **Tables** above.

**Recipe - change the breakpoint:** `768px` is repeated across the several
`@media (max-width: 768px)` blocks described above - search-and-replace it if you want a
different breakpoint. The table `@container` width (`36rem`) is separate and lives with
`.table` in the Tables section.

**Accessibility, addressed once, globally:**
- `:focus-visible` gets a visible `outline: 2px solid var(--color-primary)` on every
  link and form field (`@layer base`), `.btn` (nested `&:focus-visible` right in the
  button's own rule, `@layer components`), and matrix attendance cells (same pattern,
  next to `.table-cell-attendance`) - keyboard users always see where focus is, without
  adding a visible ring on mouse clicks.
- `@media (prefers-reduced-motion: reduce)` forces `--transition-fast` to `0s` - since
  every hover/transition in the app is built on that one token, this one override turns
  all of them off at once for users who've asked for reduced motion at the OS level.

## 11. File map

- `syncope/static/syncope/style.css` - all styling: tokens, components, utilities, responsive rules
- `syncope/static/syncope/fonts/` - self-hosted font files
- `syncope/templates/syncope/base.html` - page shell: sidebar, branding, flash messages
- `syncope/templates/syncope/_breadcrumbs.html` - breadcrumb markup (unchanged by this restyle)
- `syncope/templates/syncope/_save_bar.html` - shared draft/dirty-tracking save bar (used by `event_songs_edit.html`, `event_attendance_edit.html`)

**Pages with their own bespoke `<style>` block:** `event_meta_edit.html`, plus a small
one in `attendance_dashboard.html` for its page-only `.attendance-dashboard` flex wrapper
and a mobile `.save-bar` tweak (not table CSS). `poll_detail.html`, `poll_attendance.html`
and `attendance_dashboard.html` previously each had their own diverging table `<style>`
block (sticky columns, rotated date headers, differing pixel sizes for the same concept)
- these were consolidated into the shared `.table-matrix` system in `style.css` (see
**Tables** above), so those three pages no longer carry table-specific CSS of their own.

**Not covered in this pass** - inline `style="..."` attributes remain as they were,
follow-up work if picked back up later:
- The ~19 lower-traffic templates below the Phase 4 threshold (list/detail pages with
  fewer inline-style occurrences than the 6 worst offenders that were fixed:
  `project_update.html`, `poll_event.html`, `poll_person.html`, `poll_detail.html`,
  `poll_attendance.html`, `song_list_results.html`).
- The two checkbox/radio custom widget-template overrides (skills/roles,
  `AddAttendanceForm.attendance_type`) - currently styled via generic
  `input[type=checkbox]`/`input[type=radio]` selectors, not a bespoke aligned layout.
- A full WCAG contrast spreadsheet - only the highest-risk pairings (muted text on
  card/page backgrounds, button-label-on-fill) were actually checked against the shipped
  palette.
- Dark mode - the token names are semantic (`--color-bg`, not `--color-cream`) so it's a
  reasonable follow-up, but no dark values exist yet.
