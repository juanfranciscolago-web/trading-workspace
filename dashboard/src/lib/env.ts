/**
 * Single source of truth for the backend API base URL.
 * Reads NEXT_PUBLIC_API_BASE_URL with localhost fallback.
 * Imported by lib/api-client.ts and any hook that issues raw fetch (mutations).
 */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'
