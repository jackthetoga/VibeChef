export interface User {
  id: string
  email: string
  name?: string | null
  created_at?: string
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type?: string
}

export interface AuthResponse extends AuthTokens {
  user?: User
}

export interface Ingredient {
  id: string
  name: string
  category?: string | null
  canonical_id?: string | null
}

export interface CommonIngredient {
  name: string
  category: string
  default_quantity: number | string
  default_unit: string
}

export interface RecipeIngredient {
  id?: string
  ingredient_id?: string
  name: string
  quantity?: number | null
  unit?: string | null
  preparation?: string | null
  raw_text?: string | null
  section?: string | null
  alternate_group_id?: string | null
  in_pantry?: boolean
  match_status?: 'available' | 'insufficient' | 'unknown' | 'missing' | 'staple'
  pantry_quantity?: number | null
  pantry_unit?: string | null
  matched_via?: string | null
  conversion_basis?: string | null
  conversion_source?: string | null
  alternates?: Array<{
    ingredient_id?: string
    name: string
    quantity?: number | null
    unit?: string | null
    match_status?: string
  }> | null
}

export interface RecipeStep {
  order?: number
  step_number?: number
  instruction?: string
  description?: string
}

export interface Nutrition {
  calories?: number | null
  protein_g?: number | null
  carbs_g?: number | null
  fat_g?: number | null
  source?: 'printed' | 'estimated' | 'manual' | string | null
  basis?: 'per_serving' | 'whole_recipe' | string | null
  coverage?: number | null
}

export interface Recipe {
  id: string
  title: string
  description?: string | null
  cuisine?: string | null
  source?: string | null
  source_url?: string | null
  source_page?: number | null
  image_url?: string | null
  image_source?: string | null
  prep_time_minutes?: number | null
  cook_time_minutes?: number | null
  total_time_minutes?: number | null
  servings?: number | null
  makeable?: boolean
  missing_ingredients?: number
  ingredients?: RecipeIngredient[]
  steps?: Array<RecipeStep | string>
  nutrition?: Nutrition | null
  cookbook_id?: string
  cookbook_title?: string | null
  parse_warnings?: string[]
}

export interface CursorPage<T> {
  items: T[]
  next_cursor?: string | null
  total?: number
}

export interface RecipeFilters {
  query?: string
  makeable?: boolean
  max_missing?: number
  max_time?: number
  min_protein?: number
  cuisine?: string
  cookbook_id?: string
  sort?: 'relevance' | 'time' | 'calories' | 'protein' | 'title'
  order?: 'asc' | 'desc'
  cursor?: string
  limit?: number
}

export interface PantryItem {
  id: string
  ingredient_id?: string
  ingredient?: Ingredient
  ingredient_name?: string
  name?: string
  category?: string | null
  quantity?: number | null
  unit?: string | null
  expires_at?: string | null
  expiry_date?: string | null
  created_at?: string
}

export interface PantryInput {
  ingredient_id?: string
  ingredient_name?: string
  category?: string | null
  quantity?: number | null
  unit?: string | null
  expires_at?: string | null
}

export interface PantryBulkItem {
  name: string
  quantity?: number | null
  unit?: string | null
}

export interface PantryBulkResult {
  added: PantryItem[]
  skipped_existing: string[]
}

export interface PantryParsedChange {
  action: 'add' | 'remove'
  name: string
  quantity?: number | null
  unit?: string | null
}

export interface PantryFromTextResult {
  parsed: PantryParsedChange[]
  added: PantryItem[]
  updated: PantryItem[]
  removed: string[]
  skipped: string[]
}

export interface PantryScanItem {
  name: string
  quantity?: number | null
  unit?: string | null
  confidence?: number | null
}

export interface PantryScanResult {
  items: PantryScanItem[]
}

export interface PantryConfirmItem {
  ingredient_name: string
  quantity?: number | null
  unit?: string | null
  expires_at?: string | null
}

export interface PantryConfirmResult {
  added: PantryItem[]
  updated: PantryItem[]
  skipped_existing?: string[]
}

export interface Cookbook {
  id: string
  title?: string
  name?: string
  filename?: string
  original_filename?: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress?: number | null
  recipe_count?: number
  error?: string | null
  cover_url?: string | null
  created_at?: string
}

export interface ApiErrorBody {
  detail?: string | Array<{ msg: string; loc?: Array<string | number> }>
  message?: string
}
