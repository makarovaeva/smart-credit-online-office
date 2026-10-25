import screens from "./screens.json";
import { ScreenView } from "./screen-view";

export type ScreenName = keyof typeof screens;

// Only trusted markup extracted from the team's local HTML prototype.
// Never interpolate API data or user input into this HTML.
export function PrototypeScreen({ name }: { name: ScreenName }) {
  return <ScreenView initialName={name} />;
}

export function getScreen(name: string) {
  return Object.prototype.hasOwnProperty.call(screens, name)
    ? screens[name as ScreenName]
    : undefined;
}

export const screenNames = Object.keys(screens);
