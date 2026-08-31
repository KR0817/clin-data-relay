import {AbsoluteFill, Easing, Interactive, interpolate, useCurrentFrame, useVideoConfig} from "remotion";

const stages = [
  ["Confirmed values", "Pseudonymous fields only"],
  ["Encrypted centre package", "AES-GCM + SHA-256"],
  ["Central import ledger", "Version + duplicate checks"],
  ["Scoped Excel / EDC transfer", "Explicit operator action"],
] as const;

export const ExchangeScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  return (
    <AbsoluteFill style={{background: "linear-gradient(135deg, #07192e 0%, #0f2747 100%)", color: "#ffffff", padding: "78px 72px"}}>
      <Interactive.Div
        name="Exchange headline"
        style={{
          opacity: interpolate(frame, [0, 0.7 * fps], [0, 1], {easing: Easing.bezier(0.16, 1, 0.3, 1), extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
          translate: interpolate(frame, [0, 0.7 * fps], ["0px 22px", "0px 0px"], {easing: Easing.bezier(0.16, 1, 0.3, 1), extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
        }}
      >
        <div style={{fontSize: 16, letterSpacing: 4, color: "#5eead4", fontWeight: 780, marginBottom: 18}}>03 · EXCHANGE</div>
        <div style={{fontSize: 58, lineHeight: 1.04, fontWeight: 770, letterSpacing: -2}}>Offline centres stay governable.</div>
        <div style={{fontSize: 23, lineHeight: 1.45, color: "#c7d7ea", marginTop: 18, maxWidth: 860}}>The export package excludes original images and direct identifiers. Central import is hash-verifiable, version-aware and idempotent.</div>
      </Interactive.Div>
      <div style={{position: "absolute", left: 72, right: 72, top: 320, display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 26}}>
        {stages.map(([title, copy], index) => (
          <Interactive.Div
            key={title}
            name={`Exchange stage ${index + 1}`}
            style={{
              minHeight: 190,
              borderRadius: 22,
              padding: "28px 24px",
              backgroundColor: index === 3 ? "#0f766e" : "rgba(255, 255, 255, 0.08)",
              border: index === 3 ? "1px solid rgba(94, 234, 212, 0.58)" : "1px solid rgba(148, 163, 184, 0.26)",
              opacity: interpolate(frame, [(1.1 + index * 0.42) * fps, (1.8 + index * 0.42) * fps], [0, 1], {easing: Easing.bezier(0.16, 1, 0.3, 1), extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
              translate: interpolate(frame, [(1.1 + index * 0.42) * fps, (1.8 + index * 0.42) * fps], ["0px 30px", "0px 0px"], {easing: Easing.bezier(0.16, 1, 0.3, 1), extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
            }}
          >
            <div style={{width: 42, height: 42, borderRadius: 14, display: "grid", placeItems: "center", backgroundColor: "rgba(45, 212, 191, 0.18)", color: "#99f6e4", fontSize: 17, fontWeight: 800}}>{index + 1}</div>
            <div style={{fontSize: 22, lineHeight: 1.22, fontWeight: 720, marginTop: 28}}>{title}</div>
            <div style={{fontSize: 16, lineHeight: 1.45, color: index === 3 ? "#d7fff7" : "#aebfd3", marginTop: 12}}>{copy}</div>
          </Interactive.Div>
        ))}
      </div>
      <div style={{position: "absolute", left: 72, bottom: 74, fontSize: 16, color: "#8fa4bc"}}>Original reports stay outside every exported centre package.</div>
    </AbsoluteFill>
  );
};
