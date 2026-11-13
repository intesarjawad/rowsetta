# Design direction

Rowsetta is a tool for people who have a table and need its labels to be right.
It learns a rule from the labels, and the rule is a decision tree: rows enter at
one end, split at each test, and arrive at an answer. That is a transit network,
so the page draws it as one. The learned rule and the label audit are the same
picture.

## Steals

- **Massimo Vignelli, New York subway diagram (1972).** Track at 0 and 45
  degrees only, interchanges as white capsules, one colour per line, a black
  terminus bar with the line's roundel and name, Helvetica-like type set flat
  on white. The diagram is a diagram, not a street map: lengths are not
  distances, and nothing is shaded.
- **Charles Joseph Minard, flow maps (1869).** A band's width is the number of
  rows it carries, so the trunk and each branch say how much of the table took
  that turn.
- **Liquid glass loupe.** A thick glass tile with a curved bevel, after the
  liquid glass grid Filip Kantedal described for Codrops (September 2026). Here
  it is one lens, not a grid, and only the lens is glass.

## Signature moment: the glass over the map

When a table and target are open, the first viewport is the rule drawn as a
line map. The root is the origin on the left, labelled with the row count; each
test is an interchange; each leaf is a terminus on the right, named by the class
it answers with its row counts beside it. Each band is split into parallel lines
by the label the rows carry, in that label's line colour, proposals paler than
a person's labels.

The label audit runs once every class has at least five human labels.
Proposals and the rule start at two labels per class. A row whose label the
model doubts rides the map as a thin thread in its given label's colour, cased
in ink, on the line the rule sends it down, with its rank in a roundel at the
terminus. A Chinstrap thread on the Adelie line is visible at a glance. The
notice column says how many labels ride the wrong line and lists them in rank
order.

A glass lens sits over the map, and it shows what the flat map cannot. It is a
plain loupe: one even enlargement across its middle, so the middle is a
magnified piece of the map, where rows sit 2.4 px apart (12 times for the
penguins table, between 3 and 12 for any table). A band parts into one line
per row only where the glass sets its rows at least 1.5 px apart; otherwise it
stays one flat colour, and no line is drawn under 1 px. The selected doubted
row lifts off its line in ink casing, and the glass shows the nearest point of
that thread at its middle, so the row in question is always the one read. The
glass holds no type at all: the row's values are set in its entry in the
notice column. Drag it, or tab to the map and use the arrow keys.

The glass rests with the doubted thread through its middle, and never on a
station. When a row is picked the glass rides its thread from the origin and
rests mid-route on the thread at the first point where it covers no capsule,
no terminus, not the origin's count and not the key, and, if it can, no type
either (`restAlong` in `frontend/src/transit.ts`); of the points that pass, it
takes the one whose flat middle shows the most separate bands, where the
bands part. Where only type is in the
way, the type moves, not the glass: a station's name, or its two signs
together, step just clear of the glass, up or down, whichever is shorter, and
step back when it moves on. Only when no point on the thread passes does the
glass slide off it (`restNear`). The glass is 184 by 128 px, sized so every
doubted row in the demo has such a point. Each suggested change is reviewed
individually with Change to or Keep in the row’s reading. With nothing selected, after a ride or once a row is
let go, the glass lifts off and leaves the map clear; picking a row, the arrow
keys or a drag bring it back. All map type carries a 4 px white knockout, and steps
back by colour rather than opacity, so no thread strikes through it.

The middle is the live vector map, scaled. Around it a WebGL shader draws an
18 px bevel of clear glass from the same enlarged picture of the map, painted
on a canvas in the same frame. Toward the rim the bevel reads the map farther
and farther out, up to 1.2 bevel widths (as the steepening face of a thick
edge does), and blurs what it reads as it goes, so every band that reaches the
edge bends into it and crowds softly together there, with red, green and blue
a pixel apart. The face toward the
top-left light brightens, the opposite face darkens, a bright specular line
runs just inside the rim, strongest toward the light, the bevel fades into
the flat middle over two pixels, and a hairline ink edge closes it
(`frontend/src/lens.ts`). Without WebGL, and until the shader is ready, a flat
window with an ink ring stands in. While dragged, the glass stretches along
its motion and springs back.

The notice column carries every reading, so nothing covers the map. At an
interchange it says how many rows meet there and which way they go, in words:
"Rows with bill length up to 43.35 mm go up, the rest go down." At a terminus
it gives the line's counts and its first rows. A doubted row opens in place in
the list with one sentence, "Labelled Chinstrap, it rides the Adelie line. The
model reads it as Adelie.", each label with its line roundel, then the row's
values as stops down one ruled line, as on a strip map: a tick at each, the
value with its unit ("3900 g"), then the column's name, and Change to and Keep.
Columns are named the same way everywhere: "bill length" on the map and in the
row, "bill length mm" where no value carries the unit.

## Second moment: the re-route

Press Change to and the glass moves onto the thread first. The rest of the map steps
back to a fifth of its strength, and the moving thread is drawn 6 px wide in
ink casing. The new label's colour runs along the thread from the origin to its
terminus at an even speed, edged in white so it reads over a band of the same
colour (900 ms). Then, inside the glass, the lifted thread slides across the
band's hairlines into its new colour group (760 ms), the glass following the
thread as it goes, and the map comes back. The terminus it reaches, left in
plain view, ticks its count over once. If the fix changes the rule's shape, the old map lifts (220 ms) and the
new rule is laid from the origin rightward (1100 ms). Each change requires an
individual review: Change to applies the suggested class, and Keep leaves the
human label in place. There is no bulk correction. While the server refits,
the glass lifts off and the map holds its previous rule until the new one
lands. A progress line and the lede explain the update. Each sentence of the
headline starts its own line, and a number never leaves its noun.
When the refitted rule lands, each old
terminus whose rows now mostly reach a line that a larger old terminus also
reaches was retired. On the old map, still in place, each is struck through
and its counts read "merges into Chinstrap, 51 rows", from the old and new
rules. After two seconds they fold, one after another, into the terminus that
takes their rows, while a count over the notice's merge list runs down with
each, 13 to 9. Only then is the new map laid. The merge list stays until the
next ride or check. The headline then reports the change: "9 fixed. 4 fewer
termini."

## Tokens

- **Ground:** white `#ffffff` sheet, `#f3f4f5` for a quiet fill, ink `#0d0d0d`,
  greys `#4f5257` and `#5d6066` for what is said second, hairline `#d6d8db`,
  control edge `#7a7d83`.
- **Lines:** `#1f44b8`, `#c2410c`, `#0b7a45`, `#7b2d8e`, `#6b4f2a`, `#b0124f`,
  `#0f6e80`, `#4a4f57`, one per class in the server's class order, in
  `frontend/src/palette.ts`. Rows with no label ride `#b4b7bc`. Each carries a
  white roundel letter at 4.5:1 or more and stands at 3:1 or more on white.
- **Structure:** a 3 px ink rule over each panel, square corners, 2 px ink
  borders on buttons and fields, no gradients. A choice among a few values is a
  strip of square ink tabs sharing their edges, the chosen one solid, in place
  of a select. Paging is a pair of words on a rule. Key caps are square and
  ink-edged. Nothing casts a shadow.

## Type

Ronzino (Collletttivo, SIL OFL) at 400, 500 and 700 for everything on the page,
including the map; Spline Sans Mono (SIL OFL) only for exported code. Headline
`clamp(2.25rem, 1.6rem + 1.9vw, 3.25rem)` at 700, tight tracking. Ronzino has no
arrow glyph, so the arrow in "Chinstrap to Adelie" is a drawn SVG with the word
"to" kept for screen readers.

## Motion

Moves use `cubic-bezier(0.77, 0, 0.175, 1)`; arrivals use
`cubic-bezier(0.23, 1, 0.32, 1)`. The lens rides a doubted row's route in 1300
ms when its row is picked from the list or the table. Hover and focus changes
take 160 ms. Nothing loops. The lens redraws only when it moves or the map
changes; its wobble stops when it settles or the tab is hidden. Three.js loads
after first paint, in its own chunk. Device pixel ratio is capped at 2, and at 1
under 640 px wide.

Under `prefers-reduced-motion`, the map and lens appear finished, the lens does
not stretch, and Change to changes the label at once. Without WebGL the lens is an ink
ring around the same hairline view, so every reading still works.

## Layout

An ink app bar names the file, target and row count, and shows the model's
state as a short run of track ending at a terminus bar: solid when current,
broken while it refits. The
keyboard sheet opens from a quiet "Shortcuts" link with a `?` key cap,
the cap alone on a phone. Table and target setup comes next, expanded until
a target is selected, then collapsed behind Change table or target. The notice
column (23rem) and the map share the next viewport, with Check again and
individual Change to / Keep actions in each opened reading. The key to widths
and threads sits in the map's empty lower left, aligned to the origin. Below
that: the table, then export and the rule's lines beside accuracy, then the
leak list. Each of the
rule's lines is a vertical strip map in its line colour: a stop per test, then
the terminus bar and the answer's roundel, so each line of SQL matches a
terminus on the map. The file input is the map's origin: an ink dot and its
first stretch of track beside "Choose or drop a CSV file", with the native
input kept for keyboards and screen readers but not shown.

On the map, type stays off the track, and every station follows one rule. The
test is named once, ending just before the capsule, over or under the track
coming in. The two branch signs stand together in the fork, the upper
branch's over the lower's, centred in the gap between the two bands where the
bands have cleared them or levelled off: `≤` and `>` (or `<` and `≥` for a strict cut) for a number, `≠` and `=`
for a category, and no words. Numeric cuts use the shortest decimal boundary and comparison that agree with SQL
for every value at the full column's observed decimal precision (`splitOf`).
The SQL keeps its exact double boundary. Each placement is checked
against all the track, the capsules, the origin's count and the type already
set (`labelChoices` and `layoutMap` in `frontend/src/transit.ts`), and the map
is drawn narrower until every station's type ends before the roundel column.
Termini take two lines: the answer, then the counts. SVG labels are measured
in the rendered font and truncated to the available width, with full text in
a title. Phone route stops use the same measured truncation. Reading fields
and Change to / Keep buttons wrap, including unbroken class names. The branch signs are set
at 14 px, the names at 12. Rank roundels, 15 px across, stand in their own
column 24 px before the terminus bar, each rank in its own slot 18 px from the
next, stacked about the terminus, each joined to its thread by a short ink
leader. Rows the audit doubts
but that have too few values to place are listed under the doubts, not drawn,
so the headline and the list count the same rows.

Under 40rem the headline leads, with a still overview of the whole map under
it: laid out at desk size without type and scaled to the column, with no glass.
Its termini and rank roundels keep their desk size, the ranks side by side
before their terminus in the same 18 px slots. An opened row's values sit
16 px in from its rule.
Each doubted row then carries its own strip map, as in a train car: its
label's line, a stop per test, the terminus bar and the roundel of the line it
reaches (a dashed ring for no answer, as on the map). Below the map, the
columns to take a target from are stops on one vertical line, the picked one
filled, and the new-target fields are rules to write on.

The table keeps the existing label states, told by shape before colour: a
person's label has a solid dot in its line colour, a proposal a ring and
italic, unsure a dashed ring, and no label a short grey stretch of track. A
doubted row shows its rank roundel and a "reads Likely" button that sends the
lens to it.

## Where every number comes from

- The demo table: `uv run python scripts/mislabel_demo.py OUT.csv` writes the
  Palmer penguins table with nine species labels changed (rows 19, 77, 196,
  210, 231, 264, 285, 304 and 317, seed 7). Open it with
  `uv run rowsetta open OUT.csv` and pick `species`.
- Doubted labels, their ranks and percentages: the server's label audit
  (`GET /suspects`, `src/rowsetta/core/audit.py`), each label scored by
  the pinned TabICL model with its own row held out.
- Interchanges, termini, their tests and row counts: the distilled rule
  (`POST /distill`, `src/rowsetta/core/distill.py`), depth 4 by default,
  at most 16 leaves.
- Band widths and the "1 px for every N rows" caption: `layoutMap` in
  `frontend/src/transit.ts`, from those counts.

## What must not change

- Track runs at 0 and 45 degrees only, and a band's width is its row count.
- The map stays flat vector; only the lens is glass.
- Every number on the map is also in text: the notice column, the rule's
  lines under Export and the table. The canvas holds no text of its own.
- A label's state is told by shape and text before colour.
- Text and control edges meet WCAG 2.2 AA; `frontend/tests/tokens.contrast.test.ts`
  checks every token pair and every line colour.
- Focus is a 2 px ink outline with a 2 px offset.
- No spinners: a thin line runs for waiting, and stops under reduced motion.

## States covered

Connecting (a running line), no table (the open-a-file panel alone), an error
(an ink-bordered banner with its next step), refit in progress (the map waits
for the refit and says so, and "model updating" in the app bar), a table with
no target, insufficient class support (the audit names the missing labels), a rule with no
doubts, every doubt fixed or kept, a doubted row with most values missing
(listed with its count of missing values, not drawn as a thread), long labels
and long names (wrapped readings and controls; measured SVG ellipses with
full text in a title), and many columns. The 24-row long-value audit fixture
is checked at 390×844 and 1440×900. In
the dev server, `/?state=empty`, `error`, `refit` and `loading` show the ones
the demo server cannot hold still.
