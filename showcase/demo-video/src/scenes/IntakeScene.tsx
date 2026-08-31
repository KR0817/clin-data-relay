import {ScreenshotScene} from "../components/ScreenshotScene";

export const IntakeScene: React.FC = () => (
  <ScreenshotScene
    eyebrow="01 · CAPTURE"
    title="One queue for every report"
    body="The investigator pairs each report with a pseudonymous subject and protocol visit before extraction begins."
    bullets={[
      "Images, pulmonary-function PDFs and structured CSV",
      "Local de-identification preview before optional model use",
      "Field scope comes from the active versioned dictionary",
    ]}
    image="showcase/intake-workflow.png"
    accent="#2563eb"
  />
);
