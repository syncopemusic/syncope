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

### Build a page without writing CSS

1. Extend `base.html`; start with `<h1>` (wrap it and an "Edit" button in `.section-header`).
2. Forms: `{% for field in form %}` + `.form-group`; buttons in `.form-actions` (cancel `.btn-link`, then one `.btn-primary`); search inputs inside `.search-field`.
3. Data: `.table-container` > `.table` (+ `.table-detail`, `.table-grouped`; tables with 3 or fewer columns are narrow automatically, `.narrow` is for non-table blocks); `.col-main` on the one growing column, `.col-num`/`.col-action` on narrow ones; cards with `.card-grid` > `.card`.
4. Pages that edit data: `{% include "syncope/_save_bar.html" %}` (padding and fixed-bar behaviour come with it).
5. JS-toggled states: use the state classes (`.staged-add`, `.pending-remove`, ...). JS hooks: `js-` prefix. Hide with `hidden`.
6. No `<style>` blocks, no inline `style=`, no raw colours/px: if a class or token is missing, add it to `style.css` and to this guide.

### Theme it (future per-user or per-org style)

Append `<style>:root{ --color-primary:#2a6f97; --color-bg:#eef3f6; ... }</style>` after `style.css` in `base.html`, built from the user's or org's saved values. Only override the seed tokens listed in section 2 - everything else is derived or internal. Validate contrast of text on bg/primary before saving a theme.

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
| `--color-success-bg` / `-border` / `-text` | greens | Success flash messages |
| `--color-error-bg` / `-border` / `-text` | reds | Error flash messages |
| `--color-warning-bg` / `-border` / `-text` | ambers | Warning flash messages |
| `--color-info-bg` / `-border` / `-text` | blues | Info flash messages |
| `--color-ink` | `#3e3a34` | Dark chrome: sidebar and table headers |
| `--ink-fg` / `-fg-muted` / `-fg-faint` / `-line` / `-active` | white at 85/70/50/10/20% | Text, dividers and active/hover fills on `--color-ink` surfaces (sidebar, table header, ghost buttons) |
| `--color-attendance-0`…`-4` | see comment above them | Attendance chip colors, keyed by `AttendanceType` pk (0=TBD, 1=Present, 2=Work/School, 3=Illness, 4=Private/Vacation) - **don't reorder these**, the pk mapping is load-bearing |
| `--font-heading` / `--font-body` | see Fonts section | Typography |
| `--font-size-2xs` / `-xs` / `-sm` / `-md` / `-lg` / `-xl` | 0.75 / 0.8 / 0.85 / 0.9 / 1.1 / 1.5 rem | Text sizing scale |
| `--tracking-caps` | `0.04em` | Letter-spacing for every uppercase label (section labels, table headers, filter labels) |
| `--space-1`…`-6` | 4px → 32px | Spacing scale used for padding/margin/gap throughout |
| `--radius-sm` / `-md` / `-lg` | 6px / 10px / 999px | Corner rounding (buttons/inputs use `sm`, cards/tables use `md`, `lg` is the full pill) |
| `--shadow-sm` / `-md` | subtle box-shadows | Card and hover elevation |
| `--focus-ring` / `--focus-ring-offset` | `2px solid` primary / `2px` | The one keyboard focus outline (`:focus-visible`); text fields use a box-shadow instead |
| `--z-sticky` / `--z-mobile-drawer` / `--z-mobile-topbar` | 1 / 1000 / 1001 | The only z-index values; sticky table parts add `+1`/`+2` on top of `--z-sticky` |
| `--transition-fast` | `0.2s ease` (`0s` when `prefers-reduced-motion: reduce`) | All hover/transition timing |
| `--sidebar-width` | `250px` | Sidebar column width in `.grid-container` |
| `--field-max` | `480px` | Max width of form fields, form action row, password field/meter |
| `--content-max` | `1200px` | Max width of footer content |
| `--content-narrow` | `42rem` | Width of `.narrow` blocks (narrow tables, add panels) |
| `--tap-target` | `44px` | Minimum touch height for buttons/inputs on touch devices |
| `--save-bar-clearance` | `4rem` | Bottom padding on mobile so the fixed save bar never covers content |

**Theming (for a future per-user/org theme):** the *seed* tokens are `--color-bg`, `--color-surface`, `--color-text`, `--color-primary`, `--color-danger`, `--color-ink`, `--font-heading`, `--font-body` and `--color-attendance-0..4`. A theme is just a `<style>:root{...}</style>` overriding some of them after `style.css`. Everything else is internal. **Not yet derived:** `--color-border*`, `--color-bg-subtle`, `--color-text-muted`, `--color-primary-hover` and the status (success/error/warning/info) sets are still independent values, so a theme must override them together with the seeds (or they stay warm-beige); deriving them with `color-mix()` is the first job when the theme page is built. `--ink-*` derive from `--color-text-on-accent`, so keep that token light-on-`--color-ink`. Shadows and the page dot pattern already derive from `--color-text`. Rule for new CSS: use tokens, never raw colors or spacing values. If a value you need has no token, add a token first.

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

`style.css` is organized into six `@layer`s, declared once near the top:

```css
@layer reset, base, layout, components, state, utilities;
```

In priority order (later wins ties regardless of selector specificity): `reset` → `base` → `layout` → `components` → `state` → `utilities`. `@font-face` and the `:root` token block stay **unlayered**, above the `@layer` statement, so custom properties remain available everywhere.

| Layer | Holds |
|---|---|
| `reset` | `*` box-sizing, `body` margin reset |
| `base` | `body`/heading/link typography defaults, the single `:focus-visible` outline rule |
| `layout` | Sidebar, `.grid-container`, nav/org list, `.main-content`/`.footer`, mobile topbar/drawer shell |
| `components` | Buttons, forms, cards, alerts, breadcrumbs, save-bar, section headers, and the entire **Tables** system (below), incl. `.table-container`, `.sortable-header` |
| `state` | Deliberate overrides of components: `.sticky-col`, `.att-type-0..4`, `.table-cell-attendance-disabled`, and the JS-toggled row states `.staged-add`, `.pending-remove`, `.type-changed` (warning tint), `.row-moved`, `.dragging` (info tint) - fade amount is `--state-fade`. Add a new row state here, not on the page |
| `utilities` | One-liners: `.inline-form`, `.text-muted`, `.col-num`, `.col-action`, `.col-main`, touch-target helper |

**Why this matters if you add a rule:** a rule in a later layer (`state`, then `utilities`) always beats a same-element rule in `components`, no matter how specific the components-layer selector is - layer order is checked before specificity. If you need one rule to override another for the *same CSS property* on the same element, put both in the same layer and let normal specificity/source-order decide. Rule of thumb: if a rule exists to override a component on purpose, put it in `state`; never in `utilities`. Most of the file was moved into layers with its existing selectors unchanged - only the Tables section below got a full rewrite.

## 5. Component classes

Defined in `style.css` under clearly labeled `/* --- Section --- */` comments inside `@layer components`:

| Class | Lives under (`style.css` comment) | Use |
|---|---|---|
| `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-link`, `.btn-remove` | `/* --- Buttons --- */` | Every button/button-styled link in the app - one shared height and font, color-only modifiers. All are solid-filled, matching the surface they sit on (`--color-bg` on the page, `--color-ink` on the dark sidebar); `.btn-ghost` is the one transparent variant, for dark table headers. `.btn-remove` is the compact inline `×` used on table/formset rows, background-less by design (not a page-level action). Button text itself is pinned to `14px`/`20px` (not the `--font-size-md` rem token) so its rendered height is a clean pixel value instead of a sub-pixel one. |
| `.form-actions` | same section, right after `.btn-link` | Wraps a form's submit/cancel row - see **Forms** below for the layout rule |
| `.form-group`, `.form-help`, `ul.errorlist` styling | `/* --- Forms --- */` | Field wrapper + label + help text + Django's built-in error list |
| `.card`, `.card-grid` (+ `.card-grid-wide`), `.card-title`, `.card-strong`, `.card-field` / `.card-label` / `.card-value` | `/* --- Cards --- */` | Used by `user_dashboard.html`'s membership cards, `org_dashboard.html`'s quick-links, and `import_hub.html`'s step cards - all three share the same shape: `<h3>` title + `<p>` description + a `.btn-secondary` link as the last child. For a label/value row inside a card use `.card-field` (see `poll_attendance.html`); `.card-grid-wide` sets `--card-min: 260px` |
| `.search-field` | `/* --- Forms --- */` | Wrapper (`<span>`/`<p>`) around a live-search `<input>` + `.search-spinner`: relative positioning, grows to fill, input 100% wide. No inline styles needed |
| `.link-row` | `/* --- Buttons --- */` | Wrapping flex row, centred, `--space-2` gap - use for any button/badge/link group instead of inline flex styles |
| `.link-row-end` | `/* --- Buttons --- */` | Modifier: right-align a `.link-row` |
| `.stack` | `/* --- Buttons --- */` | Vertical flex column with `--space-3` gap - spaces a page's blocks without per-block margins |
| `.list-plain` | utilities | `<ul>` with no bullets, margin or indent |
| `.badge`, `.badge-primary`, `.badge-danger`, `.badge-circle` | `/* ... */` after the filter panel | Small pill labels and counts |
| `.breadcrumbs`, `.save-bar` | alongside `.alert` | Trail above the page; fixed bottom bar for edit pages (see **Responsive**) |
| `.chip` | inside `/* --- Tables --- */` | Clickable status pill (event attendance edit, poll attendance). Add an `.att-type-N` class for its colour; keep any `js-`/legacy hook class (`attendance-chip`, `poll-answer-btn`) alongside it for scripts |
| `.table`, `.table-detail`, `.table-grouped`, `.totals-row` | `/* --- Tables --- */` | List/detail data tables - see **Tables** below |
| `.table-matrix`, `.table-event-col`, `.table-event-header(-strong)`, `.table-cell-attendance`, `.table-row-total`, `.table-comment(-input)` | same section | The attendance/pivot grid variant - see **Tables** below |
| `.alert`, `.alert-success/-error/-warning/-info` | alongside `.messages` | Flash messages - `class="alert alert-{{ message.tags }}"` |
| `.filter-panel`, `.filter-toggle-icon` | inside `/* --- Matrix/pivot tables --- */` | Collapsible `<details>` box with a chevron that rotates when open (chevron moves left of the title on desktop). Used for the attendance and member filters, the translation cards on the lyrics edit page, and the read-only translations on `song_detail.html` |
| `.filter-form`, `.filter-row`, `.filter-row-actions`, `.filter-dates`, `.filter-label`, `.filter-reset` | same section (Matrix/pivot tables) | Layout inside a filter panel: `.filter-form` is the vertical stack, `.filter-row` a wrapping row of fields (`-actions` is the button row), `.filter-dates` groups the From/To inputs, `.filter-label` is the small muted caption, `.filter-reset` the Reset link |
| `.filter-sub`, `.filter-sub-select`, `.filter-field-limit` | same section | `.filter-sub` is a nested collapsible checkbox list (skill / voice / instrument filters), `.filter-sub-select` the select inside it (min `12rem`), `.filter-field-limit` the narrow (`90px`) event-limit number input |
| `.search-form` | `/* --- Forms --- */` | Wrapping flex row for a search input plus its buttons (song list, project participants, poll persons) |
| `.search-result-info`, `.result-count` | `/* --- Editable list rows ... --- */` and the end of the file | `.search-result-info` is the growing text block of a `.search-result-row`; `.result-count` is the muted "N results" line (`search-box.js` moves it into the page's count slot) |
| `.song-title`, `.song-subline`, `.song-meta` | `/* --- Event detail page --- */` | Two-line row text for songs, and for events in project and search lists: bold-ish title, then a small muted line (`.song-subline` spreads its children left and right; `.song-meta` is a no-wrap muted fragment) |
| `.songs-table`, `.song-resources`, `.song-actions` | `/* --- Event detail page --- */` | The event songs edit table: narrow fixed columns for number (`.song-index`, 1.3rem), resources icon (1.4rem) and actions (2.2rem) so the title column keeps the room. Other song tables keep the default `.song-index` width |
| `.drag-handle-cell` | `/* --- Tables --- */` | First column of a reorderable table: `2.2rem`, centred, holds the `.drag-handle` |
| `.table-cell-attendance-static` | `/* --- Matrix/pivot tables --- */` | A read-only attendance cell (poll detail matrix); just `cursor: default` on top of `.table-cell-attendance` |
| `.dt-full`, `.dt-short` | `/* --- Event detail page --- */` | Pair of `{% dt %}` outputs: the long date is shown on desktop and the short one at 768px and below (event detail) |
| `.event-title`, `.event-title-text` | `/* --- Event detail page --- */` | Heading row of the event, song and poll-attendance pages; `.event-title-text` truncates with an ellipsis and `.share-controls` / `.share-result` sit beside it |
| `.share-controls`, `.share-result` | `/* --- Event detail page --- */` | The Share button wrapper and the muted status text next to it ("Copying...", "Copied"), both driven by `share.js` |
| `.poll-summary`, `.project-header` | `/* --- Event detail page --- */` | Poll description line and project title: only wrap long text (`overflow-wrap: anywhere`) and tighten spacing |
| `.lyrics-columns` | `/* --- Cards --- */` | Two equal columns on the lyrics edit page (lyrics and translations), one column at 768px and below |
| `.translation-remove`, `.translation-summary-text` | `/* state */` and components | In a translation card: the Delete button (right-aligned) and the summary label, which is struck through while the card is pending removal |
| `.dirty-note` | alongside `.save-bar` | The "N unsaved changes" text in the save bar (warning colour); `save-bar.js` writes it |
| `.danger-zone` | `/* --- Buttons --- */` | Wrapper for a page's destructive action (Delete / Unlink): pushes it down by `2 x --space-6` so it sits well apart from Save |
| `.org-empty`, `.footer-info` | `layout` layer | `.org-empty` is the faint placeholder text in the sidebar when there is nothing to list; `.footer-info` caps the footer text at `--content-max` |

**Recipe - change what a button looks like everywhere:** edit `.btn` (shared shape/spacing/font) or one of `.btn-primary`/`.btn-secondary`/`.btn-danger`/`.btn-link` (color only). Every button in the app uses these - no template has its own one-off button CSS.

**Naming convention:** every component class uses plain dash-modifiers (`.btn-primary`, `.table-detail`, `.table-matrix`) - there is no BEM (`__`/`--`) anywhere in `style.css` any more. Keep new classes dash-named too.

**Hook convention:** a class either carries CSS or is a JavaScript hook, never both. Known exceptions: the state classes below, and about 20 legacy style classes that scripts also select (`btn-remove`, `btn-secondary`, `search-result-row`, `translation-panel`, `drag-handle`, `table-cell-attendance`, `song-index`, `mobile-toggle`, ...); check JS before renaming or deleting one. Hook classes have no rule in `style.css` (existing ones: `att-icon`, `att-label`, `person-picker*`, `result-label`, `pending-remove-input`, `song-row`, `quote-*-display`, `filter-count`, `field-error`, ...); name new ones with a `js-` prefix (`js-save-button`) so nobody deletes them as "unused" or styles them by accident. JS-toggled state classes use the CSS state names (`.staged-add`, `.pending-remove`, `.dirty`, `.is-active`, ...) which live in the `state` layer. `style.css` has no ID selectors: IDs are for scripts and anchors only (the save bar keeps `#dirty-actions`/`#discard-btn` for `save-bar.js`, styled through `.save-bar-dirty`/`.save-bar-discard`). Hide an element with the native `hidden` attribute; there is no `.visually-hidden` class.

## 6. Tables

All data tables share one component: `class="table"` on the `<table>` element, styled with CSS nesting (`.table { & thead th { ... } & tbody td { ... } ... }`) and a `@container` query on the sticky header/cell padding - compact by default (mobile-first), roomier once the table's `.table-container` wrapper (which declares `container-type: inline-size`) has at least `36rem` to work with. This replaced the old page-level `max-width: 768px` override that touched bare `th`/`td` selectors.

**Modifiers (used with `.table`):**
- `.table-detail` - key/value definition table (see `song_detail.html`, `org_member_detail.html`, `invitation_detail.html`)
- `.table-grouped` (+ a `group-start` class on the first `<tr>` of each group) - draws a divider between groups
- `.totals-row` (on a `<tr>`) - bold divider row for a running total
- `.narrow` (utility, any element) - caps width at `--content-narrow` (42rem); used on narrow tables and the "add" panels on edit pages

**`.table-matrix` - attendance/pivot grids:** one shared definition for the three attendance grids (`poll_detail.html`'s votes summary, `poll_attendance.html`'s single-person editor, `attendance_dashboard.html`'s full matrix), so they cannot drift apart. Add `.table-matrix` alongside `.table` (and `.table-grouped` where rows are grouped). Elements:
- `.table-event-col` on a `<th>`/`<td>` - fixed-width event column (`--table-matrix-size`)
- `.table-event-header` wrapping a rotated date/label inside a `<th>` (vertical text via `writing-mode: vertical-rl` + `rotate: 180deg`, read bottom-to-top; the header row grows to fit the text, no fixed height); add `-strong` for non-regular event types
- `.table-cell-attendance` on the clickable/status chip (`--table-matrix-size`); add `-disabled` for a non-interactive/grayed cell, or `-static` for a page where nothing is clickable at all (`poll_detail.html`)
- `.table-row-total` on a totals `<tr>` (the matrix-specific equivalent of `.totals-row`)
- `.table-comment` (read-only) / `.table-comment-input` (editable) for the small note under/in a cell
- `.legend` wraps the small "legend" of example chips above a matrix table - `.table-cell-attendance` inside `.legend` auto-sizes and drops the hover/pointer affordance

The attendance status colors themselves (`.att-type-0`…`-4`) are unchanged - see the `--color-attendance-*` token row above. Matrix table headers capitalize the same way every other `.table` header does (`text-transform: uppercase`) - there is no longer a matrix-specific exception.

**Row-number columns:** the leading `.col-num` header is left blank (no `#` text) app-wide - the row number/count still renders in the body cell below it, the header itself just doesn't repeat it. The one exception is a genuinely sortable ID column (e.g. `song_list_results.html`'s Song ID), which keeps its `ID` label and sort arrow since it's a real sortable field, not a row counter.

**Button hierarchy rule (apply this, don't reinvent per page):** one `.btn-primary` per screen (the actual commit action - Save/Update/Send/etc.), everything secondary/navigational is `.btn-link` (plain, e.g. Cancel) or `.btn-secondary` (outlined, e.g. an alternate "Return to X" action), and `.btn-danger` is reserved for destructive actions only, kept on its own confirm-delete page or behind an existing `confirm()` dialog - never placed next to a primary Save button in the same `.form-actions` row.

## 7. Utility classes

- **`.inline-form`** - replaces `style="display:inline"` on the small one-button forms scattered through detail/list pages (delete/unlink forms sitting inline with links). Purely `display: inline`.
- **Hiding wrapper `<div>`s that hold only a CSRF token:** use the native `hidden` attribute (`<div hidden>{% csrf_token %}</div>`); there is no `.visually-hidden` class.
- **Generic `input[type="checkbox"]`/`input[type="radio"]`** spacing (not a class, an element selector) - covers Django's default `CheckboxSelectMultiple`/`RadioSelect` output (skills/roles, attendance type) without a custom widget template. Slightly less polished alignment than a bespoke layout would give; a real widget-template override is the natural next step if this needs more polish later.
- **`.error`** - plain `color: var(--color-error-text)`, for hand-rolled field error messages (e.g. `<span class="error">` in `poll_form.html`).

## 8. Forms

**One field rule:** text-like `<input>`s (text, email, password, url, number, date, datetime-local, time, tel, search), `<select>` and `<textarea>` are styled by a single `:where(.form-group, form p, .search-field) :is(...)` rule in `style.css` (same for `:focus`, `.helptext`, `ul.errorlist`). To style a new input, put it inside one of those three wrappers - never add a per-input class or inline style. Add a new input type to the type list in that one rule. **Dates:** every date field uses the native picker through exactly two widgets in `forms.py`, `HtmlDateInput` (`type="date"`) and `HtmlDateTimeInput` (`type="datetime-local"`, ISO value format); never write `forms.DateInput(attrs={"type": ...})` inline. In hand-written templates use `<input type="date">` inside a `.form-group` or `.filter-field`. Compact controls (filter panel inputs/selects, table note inputs) share one thin-border recipe (`:where(.filter-field input, ...)`); add a new compact control to that list and set only its size/padding on its own class.

**The pattern:** `{% for field in form %}` + a `.form-group` wrapper, using `{{ field.errors }}` directly (Django already renders that as `<ul class="errorlist">`, which `.form-group` already styles - don't hand-loop `field.errors` yourself). See `song_meta_edit.html` and `event_meta_edit.html` for the full pattern; person fields render through the `_person_picker.html` partial (search + "+ New X" button). Plain `{{ form.as_p }}` forms (e.g. `event_form.html`, `signup.html`, `login.html`) needed no template changes at all - `style.css` styles Django's default `<p>`/`<label>`/`.errorlist`/`.helptext` output directly via `form p ...` selectors, so `.form-group` and `as_p` both render consistently without picking one convention app-wide.

**Resources:** a person, member, event, song or project's links (URL + description) are not embedded in the other forms. They are edited on their own page, `resources_edit.html` (one template for all kinds, drag to reorder, staged add/remove with the save bar), and shown read-only through `_resource_table.html` (`editable=False`; with `editable=True` it prints plain text, no links, so a click cannot leave the page with unsaved changes).

**Button row convention - `.form-actions`:** always a single `<div class="form-actions">` containing, in this DOM order: Cancel/Back link (`.btn-link`) → optional secondary link (`.btn-secondary`, e.g. a "Return to X" navigation) → the primary submit button (`.btn-primary`) last. Flexbox (`justify-content: flex-end`) renders that as cancel-left/primary-right on desktop, clustered to the right edge; on the existing 768px breakpoint `justify-content` switches to `space-between` so the same cancel-left/primary-right order spreads across the full width instead. This is deliberately the modern web convention (secondary-left/primary-right, e.g. Bootstrap/Material), not the older Windows-dialog "primary-left" pattern.

**Delete button placement:** a page-level `.btn-danger` "Delete" for the record being edited lives only on that record's own edit page (never on its detail/dashboard/list view), and sits in its own `<p>` placed *after* (below) the `.form-actions` row - the opposite side of the screen from the primary Save button, since `.form-actions` clusters right while a bare `<p>` sits left. See `org_form.html`/`event_meta_edit.html` for the pattern.

**Button labels are single words, app-wide** - not just inside `.form-group`/`.form-actions`. "Save", "Cancel", "Delete", "Update", "New", "Add", "Send", "Signup", "Unlink" etc. Where a one-word label alone would be ambiguous (e.g. multiple "New" buttons on one page), the disambiguating context goes in a nearby heading or a `title="..."` tooltip instead of stretching the button text - see the "+ New X" buttons in `_person_picker.html`, or the "New"/"Clear" search buttons in `event_songs_edit.html`/`event_attendance_edit.html`, both of which carry a `title` attribute. Plain in-page navigation links (not buttons) - e.g. "Sign up form" on the login page - are outside this rule; it only applies to actual buttons/button-styled actions.

A "return to X" navigation action (`return_url`/`return_label` in the view context) is always a plain `<a class="btn btn-secondary">`, never a `<button onclick="window.location.href=...">` - that JS was pure navigation with nothing else attached, so the link does the same job with less code. Templates carry no inline `on*=` handlers: a confirm guard is `data-confirm="..."` and a field-clearing rule is `data-clear="..."` (both handled by `ui.js`); anything with real behaviour (chips, formset row actions, save-bar tracking) is an `addEventListener` in the page script. Don't collapse those to links.

## 9. Navigation & branding

The sidebar (`syncope/templates/syncope/base.html`) is one `<nav class="sidebar">` with
four parts, top to bottom:

- `.sidebar-header` - now an `<a href="{% url 'syncope:home' %}">` wrapping the logo (`<img class="sidebar-logo">`) + `.sidebar-brand` wordmark, so clicking either takes you home
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
    `base.html`.
  - `.form-actions` switches from clustering right (`justify-content: flex-end`) to
    spreading full-width (`justify-content: space-between`) - cancel stays pinned to the
    left edge, primary to the right, same as desktop, just spread out instead of clustered.
  - Text inputs and `.btn` (all button variants) get a `--tap-target` (44px) minimum height on touch devices (`@media (pointer: coarse)`, any screen width). Full-height shells use `100dvh` so mobile browser toolbars do not cut them off.
  - Long-text textareas (`location`, `description`, `details`, `producers`, `additional_notes`) collapse to one line and grow with content (`field-sizing: content`, capped at 8 lines). To give another textarea this behaviour, add its `name` to that one selector in `style.css`.
  - The save-bar becomes `position: fixed` to the viewport bottom, and any `.main-content` that contains a `.save-bar` automatically gets `--save-bar-clearance` bottom padding (`:has()`), so pages need no per-page padding rule. On desktop the bar sits `--space-6` below the content.
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
- One `:focus-visible` rule in `@layer base` gives a `--focus-ring` outline to links, buttons,
  inputs, selects, textareas, `summary`, anything with `tabindex`, `.btn` and
  `.table-cell-attendance` - keyboard users always see where focus is, without a ring on mouse
  clicks. A new interactive component needs no focus CSS of its own; only add it to that
  selector list if it is a non-native element without `tabindex`.
- `@media (prefers-reduced-motion: reduce)` forces `--transition-fast` to `0s` - since
  every hover/transition in the app is built on that one token, this one override turns
  all of them off at once for users who've asked for reduced motion at the OS level.

## 11. File map

- `syncope/static/syncope/style.css` - all styling: tokens, then layers (`reset`, `base`, `layout`, `components`, `state`, `utilities`)
- `syncope/static/syncope/fonts/` - self-hosted font files
- `syncope/static/syncope/save-bar.js`, `search-box.js` - behaviour for the save bar and live search (hook classes, see section 5)
- `syncope/static/syncope/ui.js` - page-wide `data-` behaviour: `data-confirm="Text"` (ask before a click or submit), `data-clear="selector"` (blank sibling fields on change). Templates carry no inline `on*=` handlers; page logic uses `addEventListener`, per-element triggers use a `data-` attribute (e.g. `data-cycle` on attendance chips)
- `syncope/static/syncope/share.js` - `initShareButton({type, id})` for the Share button on detail pages
- `syncope/templates/syncope/base.html` - page shell: sidebar, branding, flash messages
- `syncope/templates/syncope/_breadcrumbs.html` - breadcrumb markup
- `syncope/templates/syncope/_save_bar.html` - shared draft/dirty-tracking save bar (included by every edit page)

**Where page-specific CSS lives:** nowhere. No template has a `<style>` block, and inline `style="..."` is limited to a few data-driven cases (`import_hub.html`'s success card, `import_dashboard.html`'s hint lines and `<pre>`, `event_list.html`'s 60% column split, `poll_attendance.html`'s `min-width: 0`). New page needs a style? Add a class to `style.css` (reuse an existing one first) and list it here.

**Auth and misc classes:** `.auth` / `.no-sidebar` (centred login/signup page without sidebar), `.auth-switch`, `.pw-field` / `.pw-eye` / `.pw-meter` (password field, eye toggle, strength bar), `.dash-head` (dashboard header card spacing), `.btn-ghost` (transparent button for dark surfaces), `.card-strong` (lighter card title for non-rehearsal events), `.btn-block` (full-width button), `.mobile-topbar` / `.mobile-toggle` (mobile header and menu button).

**Not done yet:** dark mode (tokens are semantic, but no dark values exist), custom widget templates for checkbox/radio groups, and a full WCAG contrast spreadsheet (only the highest-risk pairings were checked).
