import { steamUrl } from "../lib/format";

/** "View on Steam" link-button for a game's store page (opens in a new tab). */
export function SteamButton({ appid, name }: { appid: number; name?: string }) {
  return (
    <a
      className="button steam-button"
      href={steamUrl(appid)}
      target="_blank"
      rel="noreferrer"
      aria-label={name ? `View ${name} on Steam (opens in a new tab)` : "View on Steam (opens in a new tab)"}
    >
      View on Steam <span aria-hidden="true">↗</span>
    </a>
  );
}
