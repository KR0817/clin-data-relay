import {AbsoluteFill, Easing, Img, Interactive, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";

export const ClosingScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();

  return (
    <AbsoluteFill style={{overflow: "hidden", backgroundColor: "#07192e", color: "#ffffff"}}>
      <Img src={staticFile("showcase/central-workbench.png")} style={{position: "absolute", width: "100%", height: "100%", objectFit: "cover", opacity: 0.18, filter: "saturate(0.7)"}} />
      <div style={{position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(7,25,46,0.98) 0%, rgba(7,25,46,0.90) 55%, rgba(7,25,46,0.72) 100%)"}} />
      <Interactive.Div
        name="Closing copy"
        style={{
          position: "absolute",
          left: 88,
          top: 96,
          width: 830,
          opacity: interpolate(frame, [0, 0.9 * fps, durationInFrames - 1.2 * fps, durationInFrames], [0, 1, 1, 0], {easing: [Easing.bezier(0.16, 1, 0.3, 1), Easing.linear, Easing.linear], extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
          translate: interpolate(frame, [0, 0.9 * fps], ["0px 28px", "0px 0px"], {easing: Easing.bezier(0.16, 1, 0.3, 1), extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
        }}
      >
        <div style={{fontSize: 16, letterSpacing: 4, color: "#67e8f9", fontWeight: 780, marginBottom: 22}}>CLINDATA RELAY</div>
        <div style={{fontSize: 67, lineHeight: 1.03, fontWeight: 780, letterSpacing: -2.8}}>Faster capture.<br />Explicit control.<br />Honest boundaries.</div>
        <div style={{fontSize: 23, lineHeight: 1.48, color: "#c7d7ea", marginTop: 30, maxWidth: 720}}>Built for technical review with synthetic data. Production use remains blocked until institutional identity, validation and governance are qualified.</div>
        <div style={{display: "flex", gap: 14, marginTop: 34}}>
          <div style={{padding: "12px 18px", borderRadius: 999, backgroundColor: "#0f766e", fontSize: 16, fontWeight: 720}}>github.com/KR0817/clin-data-relay</div>
          <div style={{padding: "12px 18px", borderRadius: 999, border: "1px solid rgba(148, 163, 184, 0.42)", fontSize: 16, color: "#c7d7ea"}}>Open source · AGPL-3.0-only</div>
        </div>
      </Interactive.Div>
    </AbsoluteFill>
  );
};
