import { Composition } from "remotion";
import { TraderStory, DURATION } from "./TraderStory";

// 4:5 portrait fills the most of a phone's X feed.
export const Root = () => (
  <Composition id="TraderStory" component={TraderStory} durationInFrames={DURATION} fps={30} width={1080} height={1350} />
);
