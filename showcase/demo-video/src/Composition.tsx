import {TransitionSeries, linearTiming} from "@remotion/transitions";
import {fade} from "@remotion/transitions/fade";
import {
  AbsoluteFill,
  Interactive,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import {ArchitectureScene} from "./scenes/ArchitectureScene";
import {ClosingScene} from "./scenes/ClosingScene";
import {ExchangeScene} from "./scenes/ExchangeScene";
import {IntakeScene} from "./scenes/IntakeScene";
import {OpeningScene} from "./scenes/OpeningScene";
import {ReviewScene} from "./scenes/ReviewScene";

const Progress: React.FC = () => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();

  return (
    <Interactive.Div
      name="Video progress"
      style={{
        position: "absolute",
        left: 64,
        right: 64,
        bottom: 28,
        height: 4,
        borderRadius: 999,
        backgroundColor: "rgba(148, 163, 184, 0.24)",
        overflow: "hidden",
      }}
    >
      <Interactive.Div
        name="Video progress fill"
        style={{
          width: `${interpolate(frame, [0, durationInFrames - 1], [0, 100], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })}%`,
          height: "100%",
          borderRadius: 999,
          backgroundColor: "#2dd4bf",
        }}
      />
    </Interactive.Div>
  );
};

export const ClinDataRelayDemo: React.FC = () => {
  return (
    <AbsoluteFill style={{backgroundColor: "#07192e"}}>
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={480} name="Opening">
          <OpeningScene />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={linearTiming({durationInFrames: 18})} />
        <TransitionSeries.Sequence durationInFrames={600} name="Report intake">
          <IntakeScene />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={linearTiming({durationInFrames: 18})} />
        <TransitionSeries.Sequence durationInFrames={600} name="Candidate review">
          <ReviewScene />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={linearTiming({durationInFrames: 18})} />
        <TransitionSeries.Sequence durationInFrames={600} name="Centre exchange">
          <ExchangeScene />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={linearTiming({durationInFrames: 18})} />
        <TransitionSeries.Sequence durationInFrames={600} name="Architecture">
          <ArchitectureScene />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={linearTiming({durationInFrames: 18})} />
        <TransitionSeries.Sequence durationInFrames={810} name="Closing">
          <ClosingScene />
        </TransitionSeries.Sequence>
      </TransitionSeries>
      <Progress />
    </AbsoluteFill>
  );
};
