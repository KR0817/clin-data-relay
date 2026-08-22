# UI Skill Selection for the Clinical EDC Workbench

**Date:** 2026-08-18  
**Scope:** role-aware visual and information-architecture redesign

## Selected guidance

1. [`ui-ux-pro-max`](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)
   remains the primary design-system source. It is useful for product pattern,
   density, accessibility and responsive checks and is already installed.
2. [`frontend-design`](https://github.com/anthropics/skills/tree/main/skills/frontend-design)
   from Anthropic is installed for deliberate visual direction, typography,
   copy and self-critique. Its relevant instruction is to ground the visual
   signature in the subject rather than use a generic dashboard template.
3. [`web-design-guidelines`](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines)
   from Vercel Labs is installed for final accessibility and interface review.
4. The existing Codex in-app browser skill remains the runtime QA tool for
   viewport, keyboard, console and interaction verification.

## Considered but not selected

- OpenAI's Figma skills are official and useful when a Figma file is the visual
  source of truth. This work has no Figma asset or token handoff, so adding that
  workflow would create process without improving fidelity.
- Anthropic's web artifact builder targets standalone generated artifacts. The
  current product is an existing FastAPI and vanilla JavaScript application, so
  introducing a parallel artifact stack would duplicate the frontend.
- A framework migration, remote font, icon package or motion runtime is not
  justified. Offline centre packages, the same-origin CSP and existing browser
  contracts are product constraints.

## Applied direction

- **Subject:** multi-centre clinical research operations.
- **Audience:** site investigators, central data managers, the principal
  investigator and read-only oversight roles.
- **Single job:** make the next authorized task and its centre scope obvious.
- **Signature:** a research run strip that exposes workspace, centre scope,
  operational focus and permission boundary.
- **Implementation:** one DOM and one behavior bundle with role-aware
  projection; no copied central/site pages.
