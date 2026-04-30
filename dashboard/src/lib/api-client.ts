import type { paths } from '@/types/api'

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'

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

export async function fetcher<T>(path: string): Promise<T> {
  const url = `${BASE_URL}${path}`
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} — ${url}`)
  }
  return res.json() as Promise<T>
}
