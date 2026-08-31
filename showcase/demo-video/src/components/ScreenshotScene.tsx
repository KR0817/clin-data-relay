import {
  AbsoluteFill,
  Easing,
  Img,
  Interactive,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

type ScreenshotSceneProps = {
  eyebrow: string;
  title: string;
  body: string;
  bullets: readonly string[];
  image: string;
  accent: string;
};

export const ScreenshotScene: React.FC<ScreenshotSceneProps> = ({
  eyebrow,
  title,
  body,
  bullets,
  image,
  accent,
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();

  return (
    <AbsoluteFill
      style={{
        background: "linear-gradient(135deg, #f8fbff 0%, #eef6f8 100%)",
        color: "#0f2747",
        padding: "68px 64px 58px",
        display: "grid",
        gridTemplateColumns: "390px 1fr",
        gap: 42,
        alignItems: "center",
      }}
    >
      <Interactive.Div
        name="Scene copy"
        style={{
          opacity: interpolate(frame, [0, 0.8 * fps], [0, 1], {
            easing: Easing.bezier(0.16, 1, 0.3, 1),
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          translate: interpolate(frame, [0, 0.8 * fps], ["-26px 0px", "0px 0px"], {
            easing: Easing.bezier(0.16, 1, 0.3, 1),
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        <div style={{fontSize: 15, letterSpacing: 3, fontWeight: 750, color: accent, marginBottom: 18}}>
          {eyebrow}
        </div>
        <div style={{fontSize: 52, lineHeight: 1.06, fontWeight: 760, letterSpacing: -1.8, marginBottom: 22}}>
          {title}
        </div>
        <div style={{fontSize: 22, lineHeight: 1.45, color: "#52657d", marginBottom: 28}}>{body}</div>
        <div style={{display: "grid", gap: 13}}>
          {bullets.map((bullet, index) => (
            <div key={bullet} style={{display: "grid", gridTemplateColumns: "24px 1fr", gap: 12, alignItems: "start"}}>
              <div
                style={{
                  width: 22,
                  height: 22,
                  marginTop: 3,
                  borderRadius: 999,
                  display: "grid",
                  placeItems: "center",
                  backgroundColor: `${accent}18`,
                  color: accent,
                  fontSize: 12,
                  fontWeight: 800,
                }}
              >
                {index + 1}
              </div>
              <div style={{fontSize: 18, lineHeight: 1.45, color: "#31465f"}}>{bullet}</div>
            </div>
          ))}
        </div>
      </Interactive.Div>

      <Interactive.Div
        name="Workbench screenshot"
        style={{
          borderRadius: 24,
          overflow: "hidden",
          border: "1px solid rgba(148, 163, 184, 0.38)",
          boxShadow: "0 28px 70px rgba(15, 39, 71, 0.18)",
          backgroundColor: "#ffffff",
          opacity: interpolate(frame, [0.3 * fps, 1.2 * fps, durationInFrames - 1.2 * fps, durationInFrames], [0, 1, 1, 0.94], {
            easing: [Easing.bezier(0.16, 1, 0.3, 1), Easing.linear, Easing.linear],
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          scale: interpolate(frame, [0.3 * fps, durationInFrames], [0.965, 1.018], {
            easing: Easing.bezier(0.16, 1, 0.3, 1),
            output: "perceptual-scale",
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        <Img src={staticFile(image)} style={{display: "block", width: "100%", height: "auto"}} />
      </Interactive.Div>
    </AbsoluteFill>
  );
};
