import { API_BASE_URL } from '@/lib/env'
import type { paths } from '@/types/api'

/**
 * Extracts the application/json body of a 200 response for a given path+method.
 * Usage: Json200<'/portfolio/snapshot', 'get'>
 */
export type Json200<
  P extends keyof paths,
  M extends keyof paths[P],
> = paths[P][M] extends {
  responses: { 200: { content: { 'application/json': infer T } } }
}
  ? T
  : never

function buildUrl(
  base: string,
  path: string,
  params?: Record<string, string | number | boolean>,
): string {
  const url = `${base}${path}`
  if (!params || Object.keys(params).length === 0) {
    return url
  }
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    searchParams.append(key, String(value))
  }
  return `${url}?${searchParams.toString()}`
}

export async function fetcher<T>(
  path: string,
  params?: Record<string, string | number | boolean>,
): Promise<T> {
  const url = buildUrl(API_BASE_URL, path, params)
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`Fetch failed: ${res.status} ${res.statusText} (${path})`)
  }
  return res.json() as Promise<T>
}
