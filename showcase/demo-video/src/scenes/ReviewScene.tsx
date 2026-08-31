import {ScreenshotScene} from "../components/ScreenshotScene";

export const ReviewScene: React.FC = () => (
  <ScreenshotScene
    eyebrow="02 · REVIEW"
    title="Candidates, never silent writes"
    body="OCR and optional Kimi output stay visible as evidence-backed candidates until an authorized reviewer decides."
    bullets={[
      "Accept, edit or reject with actor and timestamp",
      "Bulk review remains policy-scoped and auditable",
      "Quality PASS / WARN / BLOCK is deterministic",
    ]}
    image="showcase/review-workflow.png"
    accent="#0f766e"
  />
);
