import { useEffect } from "react";

const SITE = "Steam Tag Analysis";
const DEFAULT_DESCRIPTION =
  "Which Steam genre mixes beat expectations, and how reception changes after launch: 60,000 games, interactive and updated monthly.";

/**
 * Per-page browser title and meta description. Link-preview crawlers only ever see
 * index.html (the route lives in the URL fragment), so this is for tabs, history and
 * search engines that run JavaScript. Pass `undefined` to leave the title to a child.
 */
export function usePageMeta(title: string | null | undefined, description?: string) {
  useEffect(() => {
    if (title === undefined) return;
    document.title = title ? `${title} · ${SITE}` : SITE;
    document.querySelector('meta[name="description"]')?.setAttribute("content", description ?? DEFAULT_DESCRIPTION);
  }, [title, description]);
}
