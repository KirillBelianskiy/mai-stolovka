// Next.js inlines this public setting when building the static Pages export.
export const apiOrigin = (process.env.NEXT_PUBLIC_API_ORIGIN ?? "").replace(/\/+$/, "");

export function apiUrl(path: string): string {
  return apiOrigin + path;
}
