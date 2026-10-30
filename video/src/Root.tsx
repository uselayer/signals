import { Composition } from "remotion";
import { TraderStory, DURATION } from "./TraderStory";
import { SameGame, SAME_GAME_DURATION } from "./SameGame";
import { Watchlist, WATCHLIST_DEFAULTS, WATCHLIST_DURATION } from "./Watchlist";
import { Nemi, NEMI_DEFAULTS, NEMI_DURATION } from "./Nemi";
import { NemiCosts, NEMI_COSTS_DEFAULTS, NEMI_COSTS_DURATION } from "./NemiCosts";

// 4:5 portrait fills the most of a phone's X feed.
export const Root = () => (
  <>
    <Composition id="TraderStory" component={TraderStory} durationInFrames={DURATION} fps={30} width={1080} height={1350} />
    <Composition id="SameGame" component={SameGame} durationInFrames={SAME_GAME_DURATION} fps={30} width={1080} height={1350} />
    {/* 16:9: most of it is the app on a desktop screen. */}
    <Composition id="Watchlist" component={Watchlist} durationInFrames={WATCHLIST_DURATION} fps={30} width={1920} height={1080}
      defaultProps={WATCHLIST_DEFAULTS} />
    <Composition id="Nemi" component={Nemi} durationInFrames={NEMI_DURATION} fps={30} width={1920} height={1080}
      defaultProps={NEMI_DEFAULTS} />
    <Composition id="NemiCosts" component={NemiCosts} durationInFrames={NEMI_COSTS_DURATION} fps={30} width={1080} height={1350}
      defaultProps={NEMI_COSTS_DEFAULTS} />
  </>
);
