import "./index.css";
import {Composition} from "remotion";
import {ClinDataRelayDemo} from "./Composition";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ClinDataRelayDemo"
      component={ClinDataRelayDemo}
      durationInFrames={3600}
      fps={30}
      width={1280}
      height={720}
    />
  );
};
