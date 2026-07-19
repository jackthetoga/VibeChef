import { useEffect, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  BookOpen,
  Clock3,
  Filter,
  Search,
  SlidersHorizontal,
  Sparkles,
  Utensils,
} from 'lucide-react'
import { cookbooksApi, recipesApi } from '../lib/api/client'
import type { Recipe, RecipeFilters } from '../lib/api/types'
import { cn, formatMinutes, useDebouncedValue } from '../lib/utils'
import { RecipeImage } from '../components/app-shell'
import { Badge, Button, Card, Dialog, Input, Select, Skeleton } from '../components/ui'

const CATEGORIES = [
  { value: '', label: 'All categories' },
  { value: 'main dish', label: 'Main dish' },
  { value: 'side dish', label: 'Side dish' },
  { value: 'salad', label: 'Salad' },
  { value: 'soup', label: 'Soup' },
  { value: 'sauce', label: 'Sauce' },
  { value: 'dessert', label: 'Dessert' },
  { value: 'breakfast', label: 'Breakfast' },
  { value: 'bread', label: 'Bread' },
  { value: 'snack', label: 'Snack' },
  { value: 'beverage', label: 'Beverage' },
] as const

const FOOD_GROUPS = [
  { value: '', label: 'All groups', className: '' },
  {
    value: 'vegetables',
    label: 'Vegetables',
    className: 'border-transparent bg-emerald-100 text-emerald-900 hover:bg-emerald-200/80',
  },
  {
    value: 'fruits',
    label: 'Fruits',
    className: 'border-transparent bg-rose-100 text-rose-900 hover:bg-rose-200/80',
  },
  {
    value: 'grains',
    label: 'Grains',
    className: 'border-transparent bg-amber-100 text-amber-950 hover:bg-amber-200/80',
  },
  {
    value: 'protein-foods',
    label: 'Protein Foods',
    className: 'border-transparent bg-violet-100 text-violet-950 hover:bg-violet-200/80',
  },
  {
    value: 'dairy',
    label: 'Dairy',
    className: 'border-transparent bg-sky-100 text-sky-950 hover:bg-sky-200/80',
  },
] as const

/** Exclusive within the row — selecting one cuisine replaces another. */
const CUISINES = [
  { value: '', label: 'All cuisines' },
  { value: 'Italian', label: 'Italian' },
  { value: 'Mexican', label: 'Mexican' },
  { value: 'Mediterranean', label: 'Mediterranean' },
  { value: 'Asian', label: 'Asian' },
  { value: 'Indian', label: 'Indian' },
  { value: 'American', label: 'American' },
  { value: 'Chinese', label: 'Chinese' },
] as const

const SORT_OPTIONS = [
  { value: 'rating:desc', label: 'Highest source rating', sort: 'rating' as const, order: 'desc' as const },
  { value: 'relevance:asc', label: 'Best match', sort: 'relevance' as const, order: 'asc' as const },
  { value: 'time:asc', label: 'Fastest', sort: 'time' as const, order: 'asc' as const },
  { value: 'protein:desc', label: 'Most protein', sort: 'protein' as const, order: 'desc' as const },
  { value: 'calories:asc', label: 'Lowest calories', sort: 'calories' as const, order: 'asc' as const },
  { value: 'title:asc', label: 'Name A–Z', sort: 'title' as const, order: 'asc' as const },
]

const DEFAULT_FILTERS: RecipeFilters = { sort: 'rating', order: 'desc' }
const HIGH_PROTEIN_GRAMS = 20
const BROWSE_STATE_KEY = 'recipe-finder.recipes-browse'

const SORT_VALUES = new Set(['relevance', 'time', 'calories', 'protein', 'title', 'rating'])
const ORDER_VALUES = new Set(['asc', 'desc'])

type BrowseState = {
  search: string
  filters: RecipeFilters
}

function sanitizeFilters(value: unknown): RecipeFilters {
  if (!value || typeof value !== 'object') return { ...DEFAULT_FILTERS }
  const input = value as Record<string, unknown>
  const filters: RecipeFilters = { ...DEFAULT_FILTERS }

  if (typeof input.makeable === 'boolean') filters.makeable = input.makeable || undefined
  if (typeof input.max_missing === 'number' && Number.isFinite(input.max_missing)) {
    filters.max_missing = input.max_missing
  }
  if (typeof input.max_time === 'number' && Number.isFinite(input.max_time)) {
    filters.max_time = input.max_time
  }
  if (typeof input.min_protein === 'number' && Number.isFinite(input.min_protein)) {
    filters.min_protein = input.min_protein
  }
  if (typeof input.cuisine === 'string' && input.cuisine) filters.cuisine = input.cuisine
  if (typeof input.category === 'string' && input.category) filters.category = input.category
  if (typeof input.food_group === 'string' && input.food_group) filters.food_group = input.food_group
  if (typeof input.cookbook_id === 'string' && input.cookbook_id) {
    filters.cookbook_id = input.cookbook_id
  }
  if (typeof input.sort === 'string' && SORT_VALUES.has(input.sort)) {
    filters.sort = input.sort as RecipeFilters['sort']
  }
  if (typeof input.order === 'string' && ORDER_VALUES.has(input.order)) {
    filters.order = input.order as RecipeFilters['order']
  }
  if (Array.isArray(input.tag)) {
    const tags = input.tag.filter((tag): tag is string => typeof tag === 'string' && Boolean(tag))
    if (tags.length) filters.tag = tags
  }

  return filters
}

function loadBrowseState(): BrowseState {
  try {
    const raw = sessionStorage.getItem(BROWSE_STATE_KEY)
    if (!raw) return { search: '', filters: { ...DEFAULT_FILTERS } }
    const parsed = JSON.parse(raw) as { search?: unknown; filters?: unknown }
    return {
      search: typeof parsed.search === 'string' ? parsed.search : '',
      filters: sanitizeFilters(parsed.filters),
    }
  } catch {
    return { search: '', filters: { ...DEFAULT_FILTERS } }
  }
}

function saveBrowseState(state: BrowseState) {
  try {
    sessionStorage.setItem(BROWSE_STATE_KEY, JSON.stringify(state))
  } catch {
    // Ignore quota / private-mode failures; filters still work for the current mount.
  }
}

function FilterChip({
  active,
  onClick,
  children,
  className,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
  className?: string
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'shrink-0 rounded-full border px-3.5 py-1.5 text-sm font-semibold transition',
        active
          ? 'border-ink bg-ink text-cream shadow-sm'
          : 'border-line bg-white text-ink hover:bg-sand',
        !active && className,
      )}
    >
      {children}
    </button>
  )
}

function MoreFilterFields({
  filters,
  setFilters,
  cookbooks,
}: {
  filters: RecipeFilters
  setFilters: React.Dispatch<React.SetStateAction<RecipeFilters>>
  cookbooks: Array<{ id: string; title: string }>
}) {
  const set = <K extends keyof RecipeFilters>(key: K, value: RecipeFilters[K]) =>
    setFilters((current) => ({ ...current, [key]: value }))
  return (
    <div className="grid min-w-0 gap-5">
      <label className="flex min-w-0 cursor-pointer items-center justify-between gap-3 rounded-xl bg-sand p-3 text-sm font-bold text-ink">
        <span className="min-w-0">I can make it now</span>
        <input
          type="checkbox"
          className="size-4 shrink-0 accent-sage"
          checked={filters.makeable || false}
          onChange={(event) => set('makeable', event.target.checked || undefined)}
        />
      </label>
      <label className="grid min-w-0 gap-2 text-sm font-bold text-ink">
        Cookbook
        <Select
          className="w-full max-w-full"
          value={filters.cookbook_id || ''}
          onChange={(event) => set('cookbook_id', event.target.value || undefined)}
        >
          <option value="">All cookbooks</option>
          {cookbooks.map((book) => (
            <option key={book.id} value={book.id} title={book.title}>
              {book.title.length > 42 ? `${book.title.slice(0, 39)}…` : book.title}
            </option>
          ))}
        </Select>
      </label>
      <label className="grid min-w-0 gap-2 text-sm font-bold text-ink">
        Max missing ingredients
        <div className="flex min-w-0 items-center gap-3">
          <input
            className="min-w-0 flex-1 accent-sage"
            type="range"
            min="0"
            max="10"
            value={filters.max_missing ?? 10}
            onChange={(event) =>
              set('max_missing', Number(event.target.value) === 10 ? undefined : Number(event.target.value))
            }
          />
          <span className="w-8 shrink-0 text-right text-muted">{filters.max_missing ?? 'Any'}</span>
        </div>
      </label>
      <label className="grid min-w-0 gap-2 text-sm font-bold text-ink">
        Ready within
        <Select
          className="w-full max-w-full"
          value={filters.max_time || ''}
          onChange={(event) => set('max_time', Number(event.target.value) || undefined)}
        >
          <option value="">Any time</option>
          <option value="15">15 minutes</option>
          <option value="30">30 minutes</option>
          <option value="45">45 minutes</option>
          <option value="60">1 hour</option>
        </Select>
      </label>
    </div>
  )
}

export function RecipeCard({ recipe }: { recipe: Recipe }) {
  const missing = recipe.missing_ingredients || 0
  const time =
    recipe.total_time_minutes ||
    (recipe.prep_time_minutes || 0) + (recipe.cook_time_minutes || 0)
  return (
    <Link to="/recipes/$recipeId" params={{ recipeId: recipe.id }} className="group block">
      <Card className="h-full overflow-hidden transition duration-300 hover:-translate-y-1 hover:shadow-lg">
        <RecipeImage
          recipeId={recipe.id}
          imageUrl={recipe.image_url}
          seed={recipe.id || recipe.title}
          className="aspect-[16/10] border-b border-line"
        />
        <div className="p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <Badge tone={recipe.makeable || missing === 0 ? 'green' : 'amber'}>
              {recipe.makeable || missing === 0 ? (
                <>
                  <Sparkles className="mr-1 size-3" /> Makeable
                </>
              ) : (
                `${missing} missing`
              )}
            </Badge>
            {recipe.cuisine && <span className="text-xs font-semibold text-muted">{recipe.cuisine}</span>}
          </div>
          <h2 className="line-clamp-2 font-display text-xl font-bold leading-tight text-ink group-hover:text-sage-dark">
            {recipe.title}
          </h2>
          {recipe.cookbook_title && (
            <p className="mt-2 flex items-center gap-1.5 truncate text-xs font-semibold text-muted">
              <BookOpen className="size-3.5 shrink-0" /> {recipe.cookbook_title}
            </p>
          )}
          <div className="mt-4 flex items-center gap-4 border-t border-line pt-3 text-xs font-semibold text-muted">
            <span className="flex items-center gap-1.5">
              <Clock3 className="size-4" /> {formatMinutes(time)}
            </span>
            <span className="flex items-center gap-1.5">
              <Utensils className="size-4" /> {recipe.nutrition?.protein_g ?? '—'}g protein
              {recipe.nutrition?.source === 'estimated' ? ' · est.' : ''}
            </span>
          </div>
        </div>
      </Card>
    </Link>
  )
}

function RecipeSkeletons() {
  return (
    <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: 6 }, (_, index) => (
        <Card key={index} className="overflow-hidden p-0">
          <Skeleton className="aspect-[16/10] rounded-none" />
          <div className="grid gap-3 p-4">
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-7 w-4/5" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </Card>
      ))}
    </div>
  )
}

export function RecipesPage() {
  const [browse, setBrowse] = useState(loadBrowseState)
  const { search, filters } = browse
  const setSearch = (value: React.SetStateAction<string>) =>
    setBrowse((current) => ({
      ...current,
      search: typeof value === 'function' ? value(current.search) : value,
    }))
  const setFilters = (value: React.SetStateAction<RecipeFilters>) =>
    setBrowse((current) => ({
      ...current,
      filters: typeof value === 'function' ? value(current.filters) : value,
    }))
  const [moreOpen, setMoreOpen] = useState(false)
  const query = useDebouncedValue(search.trim())
  const activeFilters = Object.entries(filters).filter(
    ([key, value]) => !['sort', 'order'].includes(key) && value !== undefined && value !== '',
  ).length
  const cookbooks = useQuery({
    queryKey: ['cookbooks'],
    queryFn: cookbooksApi.list,
  })
  const cookbookOptions = (cookbooks.data?.items || []).map((book) => ({
    id: book.id,
    title: book.title || book.name || book.original_filename || book.filename || 'Untitled cookbook',
  }))

  useEffect(() => {
    saveBrowseState({ search, filters })
  }, [search, filters])

  const recipes = useInfiniteQuery({
    queryKey: ['recipes', query, filters],
    queryFn: ({ pageParam }) =>
      recipesApi.list({ ...filters, query: query || undefined, cursor: pageParam, limit: 18 }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor || undefined,
  })
  const items = recipes.data?.pages.flatMap((page) => page.items) || []
  const hasLibrary = (cookbooks.data?.items.length || 0) > 0
  const hasActiveSearch = Boolean(query) || activeFilters > 0
  const highProtein = filters.min_protein === HIGH_PROTEIN_GRAMS
  const sortValue = `${filters.sort || 'rating'}:${filters.order || 'desc'}`

  const clearBrowseFilters = () =>
    setFilters((current) => ({
      sort: current.sort,
      order: current.order,
    }))

  return (
    <div className="mx-auto max-w-[1500px] p-4 sm:p-7 xl:p-10">
      <div className="mb-8">
        <p className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[.18em] text-terracotta">
          <Sparkles className="size-4" /> Your kitchen, your recipes
        </p>
        <h1 className="font-display text-4xl font-bold tracking-tight text-ink sm:text-5xl">What are we cooking?</h1>
        <p className="mt-2 max-w-xl text-muted">Search your cookbooks and discover meals you can make right now.</p>
      </div>

      <div className="relative mb-5">
        <Search className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-muted" />
        <Input
          className="h-14 rounded-2xl pl-12 pr-4 text-base shadow-sm"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search recipes by name or ingredient..."
          aria-label="Search recipes"
        />
      </div>

      <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Dish category">
        {CATEGORIES.map((category) => (
          <FilterChip
            key={category.value || 'all-categories'}
            active={(filters.category || '') === category.value}
            onClick={() =>
              setFilters((current) => ({
                ...current,
                category: category.value || undefined,
              }))
            }
          >
            {category.label}
          </FilterChip>
        ))}
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2" role="group" aria-label="Food group">
        {FOOD_GROUPS.map((group) => (
          <FilterChip
            key={group.value || 'all-groups'}
            active={(filters.food_group || '') === group.value}
            className={group.className}
            onClick={() =>
              setFilters((current) => ({
                ...current,
                food_group: group.value || undefined,
              }))
            }
          >
            {group.label}
          </FilterChip>
        ))}
        <FilterChip
          active={highProtein}
          className="border-leaf/40 bg-white text-leaf-dark hover:bg-leaf/10"
          onClick={() =>
            setFilters((current) => ({
              ...current,
              min_protein: highProtein ? undefined : HIGH_PROTEIN_GRAMS,
            }))
          }
        >
          High protein (20g+)
        </FilterChip>
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-2" role="group" aria-label="Cuisine">
        {CUISINES.map((cuisine) => (
          <FilterChip
            key={cuisine.value || 'all-cuisines'}
            active={(filters.cuisine || '') === cuisine.value}
            onClick={() =>
              setFilters((current) => ({
                ...current,
                // Exclusive: only one cuisine at a time (replaces previous).
                cuisine: cuisine.value || undefined,
              }))
            }
          >
            {cuisine.label}
          </FilterChip>
        ))}
      </div>

      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm font-semibold text-muted" aria-live="polite">
            {recipes.isLoading
              ? 'Finding recipes…'
              : `${items.length.toLocaleString()}${recipes.hasNextPage ? '+' : ''} recipes`}
          </p>
          {activeFilters > 0 && (
            <button
              type="button"
              className="text-xs font-bold text-terracotta"
              onClick={clearBrowseFilters}
            >
              Clear filters
            </button>
          )}
          <Button variant="secondary" size="sm" onClick={() => setMoreOpen(true)}>
            <SlidersHorizontal className="size-4" />
            More {activeFilters ? `(${activeFilters})` : ''}
          </Button>
        </div>
        <label className="flex items-center gap-2 text-sm font-semibold text-ink">
          <span className="text-muted">Sort:</span>
          <Select
            aria-label="Sort recipes"
            className="min-w-[10.5rem]"
            value={SORT_OPTIONS.some((option) => option.value === sortValue) ? sortValue : 'rating:desc'}
            onChange={(event) => {
              const selected = SORT_OPTIONS.find((option) => option.value === event.target.value)
              if (!selected) return
              setFilters((current) => ({
                ...current,
                sort: selected.sort,
                order: selected.order,
              }))
            }}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </label>
      </div>

      <section className="min-w-0" aria-live="polite">
        {recipes.isLoading ? (
          <RecipeSkeletons />
        ) : recipes.isError ? (
          <Card className="grid place-items-center p-10 text-center">
            <p className="font-display text-xl font-bold text-ink">We couldn’t load your recipes</p>
            <p className="mt-2 text-sm text-muted">{recipes.error.message}</p>
            <Button className="mt-5" onClick={() => void recipes.refetch()}>Try again</Button>
          </Card>
        ) : items.length === 0 && !hasLibrary ? (
          <Card className="grid place-items-center p-12 text-center">
            <span className="grid size-14 place-items-center rounded-full bg-sand text-sage-dark">
              <BookOpen className="size-6" />
            </span>
            <p className="mt-4 font-display text-2xl font-bold text-ink">No cookbooks yet</p>
            <p className="mt-2 max-w-sm text-sm text-muted">
              Upload a PDF, EPUB, or TXT cookbook to start building your recipe shelf.
            </p>
            <Link
              to="/library"
              className="mt-5 inline-flex h-11 items-center rounded-xl bg-ink px-4 text-sm font-semibold text-cream"
            >
              Go to library
            </Link>
          </Card>
        ) : items.length === 0 ? (
          <Card className="grid place-items-center p-12 text-center">
            <span className="grid size-14 place-items-center rounded-full bg-sand text-sage-dark">
              <Search className="size-6" />
            </span>
            <p className="mt-4 font-display text-2xl font-bold text-ink">No recipes found</p>
            <p className="mt-2 max-w-sm text-sm text-muted">
              {hasActiveSearch
                ? 'Try a broader search or clear a few filters.'
                : 'Your cookbooks are still importing, or none had extractable recipes yet.'}
            </p>
            {hasActiveSearch ? (
              <Button
                className="mt-5"
                variant="secondary"
                onClick={() => {
                  setSearch('')
                  setFilters(DEFAULT_FILTERS)
                }}
              >
                Clear search
              </Button>
            ) : (
              <Link
                to="/library"
                className="mt-5 inline-flex h-11 items-center rounded-xl border border-line bg-white px-4 text-sm font-semibold text-ink"
              >
                Check library
              </Link>
            )}
          </Card>
        ) : (
          <>
            <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
              {items.map((recipe) => <RecipeCard key={recipe.id} recipe={recipe} />)}
            </div>
            {recipes.hasNextPage && (
              <div className="mt-8 text-center">
                <Button
                  variant="secondary"
                  disabled={recipes.isFetchingNextPage}
                  onClick={() => void recipes.fetchNextPage()}
                >
                  {recipes.isFetchingNextPage ? 'Loading…' : 'Load more recipes'}
                </Button>
              </div>
            )}
          </>
        )}
      </section>

      <Dialog open={moreOpen} onClose={() => setMoreOpen(false)} title="More filters">
        <MoreFilterFields filters={filters} setFilters={setFilters} cookbooks={cookbookOptions} />
        <Button className="mt-6 w-full" onClick={() => setMoreOpen(false)}>
          <Filter className="size-4" /> Show recipes
        </Button>
      </Dialog>
    </div>
  )
}
