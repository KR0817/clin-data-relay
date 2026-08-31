import {AbsoluteFill, Easing, Img, Interactive, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";

export const ArchitectureScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();

  return (
    <AbsoluteFill style={{backgroundColor: "#eaf2f6", padding: "52px 62px"}}>
      <Interactive.Div
        name="Architecture frame"
        style={{
          width: "100%",
          height: "100%",
          borderRadius: 26,
          overflow: "hidden",
          backgroundColor: "#ffffff",
          boxShadow: "0 28px 70px rgba(15, 39, 71, 0.17)",
          opacity: interpolate(frame, [0, 0.9 * fps], [0, 1], {easing: Easing.bezier(0.16, 1, 0.3, 1), extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
          scale: interpolate(frame, [0, durationInFrames], [0.97, 1.02], {easing: Easing.bezier(0.16, 1, 0.3, 1), output: "perceptual-scale", extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
        }}
      >
        <Img src={staticFile("architecture.svg")} style={{display: "block", width: "100%", height: "100%", objectFit: "cover"}} />
      </Interactive.Div>
      <div style={{position: "absolute", right: 92, top: 78, padding: "9px 16px", borderRadius: 999, backgroundColor: "#0f2747", color: "#ffffff", fontSize: 14, letterSpacing: 2, fontWeight: 750}}>04 · AUTHORITY</div>
    </AbsoluteFill>
  );
};
