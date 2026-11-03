import { Composition } from "remotion";
import { TraderStory, DURATION } from "./TraderStory";
import { SameGame, SAME_GAME_DURATION } from "./SameGame";
import { Watchlist, WATCHLIST_DEFAULTS, WATCHLIST_DURATION } from "./Watchlist";
import { EveryVenue, EVERY_VENUE_DEFAULTS, EVERY_VENUE_DURATION } from "./EveryVenue";
import { OneSchema, ONE_SCHEMA_DEFAULTS, ONE_SCHEMA_DURATION } from "./OneSchema";
import { OneSchemaDark, ONE_SCHEMA_DARK_DURATION } from "./OneSchemaDark";

// 4:5 portrait fills the most of a phone's X feed.
export const Root = () => (
  <>
    <Composition id="TraderStory" component={TraderStory} durationInFrames={DURATION} fps={30} width={1080} height={1350} />
    <Composition id="OneSchemaDark" component={OneSchemaDark} durationInFrames={ONE_SCHEMA_DARK_DURATION} fps={30} width={1080} height={1350} />
    <Composition id="OneSchema" component={OneSchema} durationInFrames={ONE_SCHEMA_DURATION} fps={30} width={1080} height={1350}
      defaultProps={ONE_SCHEMA_DEFAULTS} />
    <Composition id="EveryVenue" component={EveryVenue} durationInFrames={EVERY_VENUE_DURATION} fps={30} width={1080} height={1350}
      defaultProps={EVERY_VENUE_DEFAULTS} />
    <Composition id="SameGame" component={SameGame} durationInFrames={SAME_GAME_DURATION} fps={30} width={1080} height={1350} />
    {/* 16:9: most of it is the app on a desktop screen. */}
    <Composition id="Watchlist" component={Watchlist} durationInFrames={WATCHLIST_DURATION} fps={30} width={1920} height={1080}
      defaultProps={WATCHLIST_DEFAULTS} />
  </>
);
