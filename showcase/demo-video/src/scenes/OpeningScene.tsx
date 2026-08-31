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

export const OpeningScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  return (
    <AbsoluteFill style={{overflow: "hidden", background: "linear-gradient(135deg, #07192e 0%, #0f2747 58%, #0f766e 140%)", color: "#ffffff", padding: "82px 72px"}}>
      <div style={{position: "absolute", width: 520, height: 520, borderRadius: 999, right: -120, top: -190, background: "rgba(45, 212, 191, 0.12)"}} />
      <div style={{position: "absolute", width: 360, height: 360, borderRadius: 999, right: 120, bottom: -250, background: "rgba(96, 165, 250, 0.12)"}} />
      <Interactive.Div
        name="Opening title"
        style={{
          position: "absolute",
          left: 72,
          top: 108,
          width: 560,
          opacity: interpolate(frame, [0, 0.9 * fps], [0, 1], {easing: Easing.bezier(0.16, 1, 0.3, 1), extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
          translate: interpolate(frame, [0, 0.9 * fps], ["0px 28px", "0px 0px"], {easing: Easing.bezier(0.16, 1, 0.3, 1), extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
        }}
      >
        <div style={{fontSize: 16, letterSpacing: 4, color: "#67e8f9", fontWeight: 780, marginBottom: 22}}>CLINDATA RELAY</div>
        <div style={{fontSize: 70, lineHeight: 1.02, fontWeight: 780, letterSpacing: -2.8, marginBottom: 28}}>Clinical data, with a human in control.</div>
        <div style={{fontSize: 25, lineHeight: 1.45, color: "#c7d7ea"}}>A two-minute tour of a local-first companion for multicentre investigator-initiated research.</div>
        <div style={{display: "inline-flex", marginTop: 32, borderRadius: 999, padding: "11px 18px", backgroundColor: "rgba(45, 212, 191, 0.14)", border: "1px solid rgba(94, 234, 212, 0.4)", fontSize: 15, fontWeight: 700, color: "#99f6e4"}}>Synthetic data only · Research prototype</div>
      </Interactive.Div>
      <Interactive.Div
        name="Opening architecture preview"
        style={{
          position: "absolute",
          width: 650,
          right: -62,
          top: 126,
          borderRadius: 26,
          overflow: "hidden",
          boxShadow: "0 34px 90px rgba(0, 0, 0, 0.34)",
          opacity: interpolate(frame, [0.6 * fps, 1.6 * fps], [0, 1], {easing: Easing.bezier(0.16, 1, 0.3, 1), extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
          translate: interpolate(frame, [0.6 * fps, 1.6 * fps], ["48px 0px", "0px 0px"], {easing: Easing.bezier(0.16, 1, 0.3, 1), extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
          rotate: "-2deg",
        }}
      >
        <Img src={staticFile("architecture.svg")} style={{display: "block", width: "100%"}} />
      </Interactive.Div>
    </AbsoluteFill>
  );
};
