/** Absolute URL of a file in web/public/data, respecting the deploy base path. */
export function dataUrl(file: string): string {
  return new URL(`${import.meta.env.BASE_URL}data/${file}`, window.location.href).href;
}
