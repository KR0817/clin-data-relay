# Workbench Page Override

This file overrides `../MASTER.md` only for the authenticated workbench.

## Subject and job

- Subject: multi-centre clinical research operations.
- Audience: centre investigators, central coordination and read-only oversight.
- Primary job: show the next authorized task and the exact centre scope.

## Compact token system

| Token | Central | Site | Oversight |
|---|---|---|---|
| Workspace accent | `#0F766E` | `#2563EB` | `#475467` |
| Accent surface | `#ECFDF5` | `#EFF6FF` | `#F2F4F7` |
| Accent border | `#99F6E4` | `#BFDBFE` | `#D0D5DD` |

- Display and body: offline system UI stack from the master file.
- Data and centre identifiers: installed monospace fallback stack.
- Body copy remains 13–14 px; labels and metadata remain 11–12 px.

## Layout

```text
+--------------------------------------------------------------+
| Product header                              Environment       |
+--------------------------------------------------------------+
| Session and integrations                 Export / Exchange    |
+--------------------------------------------------------------+
| Workspace | Centre scope | Current focus | Permission | CTA   |
+--------------------------------------------------------------+
| Role-aware same-page navigation                              |
+--------------------------------------------------------------+
| Existing workflow sections                                   |
+--------------------------------------------------------------+
```

## Signature element

The research run strip is the single distinctive element. Its left rule and
small scope marker recall a controlled study run sheet without imitating an
EHR. All other surfaces stay quiet and operational.

Three audited Dreamina derivatives may support this element without becoming
the element itself:

- Central/oversight context: a quiet right-weighted research-network field in
  navy, teal and cyan.
- Site context: a quiet right-weighted document-to-structured-data field in
  navy, blue and cyan.
- Review empty state: a compact evidence-convergence illustration on a plain
  surface.

All are abstract, text-free, people-free and de-identified. Context artwork is
kept below 18% opacity behind a solid readability gradient. Empty-state artwork
is bounded to 168 px on desktop and 120 px on mobile. No artwork is attached to
success, warning, error or permission semantics.

## Interaction rules

- Central and oversight sessions open operations on login; site sessions do
  not steal focus from report intake.
- Navigation order equals keyboard order. Labels may change by role, but links
  continue to target the existing section IDs.
- Never hide an authorization error behind presentation logic.
- Use no runtime remote asset, new dependency or decorative motion. Generated
  source material is audited once and shipped only as a same-origin WebP
  derivative.

## Compact command-deck override

- Keep identity and Kimi readiness visible; place detailed EDC and production
  diagnostics in one native disclosure labelled `系统状态`.
- Treat the first viewport as an operations console: reduce ornamental header
  height and repeated padding before reducing clinical form density.
- On phones, use a two-column session-action grid, a one-row bounded navigation
  scroller and a one-row four-step rail. Preserve 44 px interactive targets,
  visible focus and page-level overflow containment.
- The permission boundary remains visible in the research run strip; on phones
  it spans the full width below centre and current-focus facts.
