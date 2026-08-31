# ClinData Relay demo video

This Remotion project is the reproducible source for the two-minute public
product tour. It uses synthetic screenshots and contains no patient data.

Install locked dependencies:

```bash
npm ci
```

Preview:

```bash
npm run dev
```

Validate and render the checked-in MP4:

```bash
npm run lint
npm run render
```

The composition is 3,600 frames at 30 fps (two minutes), 1280x720, and renders
to `../../docs/demo/clin-data-relay-demo.mp4`. Remotion licensing is separate
from this repository license; review the upstream terms before commercial use.
