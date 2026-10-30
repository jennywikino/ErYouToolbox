export interface Game { name: string; game_id: number }
export interface Preview { image_url: string; thumbnail_url: string; switch_url: string }
export interface Mod {
  is_read?: boolean | number
  rank?: number; metrics?: {likes?: number; views?: number}; is_local?: boolean
  ranking_scope?: 'recent_sample'
  source_ratings?: {codes: string[]; verification: string}

  source: string; item_type: string; item_id: number; game_id: number | null
  game_name: string | null; title: string | null; author_name: string | null
  author_id: number | null; author_url: string | null; original_url: string | null
  created_at: string | null; updated_at: string | null; first_seen_at?: string
  source_update_detected_at?: string | null
  subscription_followed_at?: string
  author_baseline_at?: string | null
  local_first_seen_event_at?: string | null
  version: string | null; category: string | null; subcategory: string | null
  content_rating_status: string; preview_state: string; preview_urls: string[]
  preview_images?: Preview[]; image_count: number; tags?: string[]; description?: string | null
}
export interface ModPage {
  items: Mod[]; total_count: number; limit: number; offset: number
  discovery?: {local_count: number; game_id: number | null; coverage: 'unverified';
    last_sync: {source: string; game_id: number | null; started_at: string; ended_at: string | null; status: string} | null}
}
