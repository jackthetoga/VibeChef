import { useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  ArrowDownAZ,
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
import { formatMinutes, useDebouncedValue } from '../lib/utils'
import { RecipeArt } from '../components/app-shell'
import { Badge, Button, Card, Dialog, Input, Select, Skeleton } from '../components/ui'

const cuisines = ['', 'Italian', 'Mexican', 'Mediterranean', 'Asian', 'Indian', 'American']

function FilterFields({
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
      <label className="grid min-w-0 gap-2 text-sm font-bold text-ink">
        Minimum protein
        <Select
          className="w-full max-w-full"
          value={filters.min_protein || ''}
          onChange={(event) => set('min_protein', Number(event.target.value) || undefined)}
        >
          <option value="">Any amount</option>
          <option value="15">15g+</option>
          <option value="25">25g+</option>
          <option value="40">40g+</option>
        </Select>
      </label>
      <label className="grid min-w-0 gap-2 text-sm font-bold text-ink">
        Cuisine
        <Select
          className="w-full max-w-full"
          value={filters.cuisine || ''}
          onChange={(event) => set('cuisine', event.target.value || undefined)}
        >
          {cuisines.map((cuisine) => (
            <option key={cuisine} value={cuisine}>
              {cuisine || 'All cuisines'}
            </option>
          ))}
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
        <RecipeArt seed={recipe.id || recipe.title} className="aspect-[16/10] border-b border-line" />
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
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<RecipeFilters>({ sort: 'relevance', order: 'asc' })
  const [filtersOpen, setFiltersOpen] = useState(false)
  const query = useDebouncedValue(search.trim())
  const activeFilters = Object.entries(filters).filter(
    ([key, value]) => !['sort', 'order'].includes(key) && value !== undefined,
  ).length
  const cookbooks = useQuery({
    queryKey: ['cookbooks'],
    queryFn: cookbooksApi.list,
  })
  const cookbookOptions = (cookbooks.data?.items || []).map((book) => ({
    id: book.id,
    title: book.title || book.name || book.original_filename || book.filename || 'Untitled cookbook',
  }))

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

  return (
    <div className="mx-auto max-w-[1500px] p-4 sm:p-7 xl:p-10">
      <div className="mb-8 flex flex-col justify-between gap-5 xl:flex-row xl:items-end">
        <div>
          <p className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[.18em] text-terracotta">
            <Sparkles className="size-4" /> Your kitchen, your recipes
          </p>
          <h1 className="font-display text-4xl font-bold tracking-tight text-ink sm:text-5xl">What are we cooking?</h1>
          <p className="mt-2 max-w-xl text-muted">Search your cookbooks and discover meals you can make right now.</p>
        </div>
        <div className="flex gap-2">
          <Select
            aria-label="Sort recipes"
            value={filters.sort}
            onChange={(event) => {
              const sort = event.target.value as RecipeFilters['sort']
              setFilters((value) => ({
                ...value,
                sort,
                order: sort === 'protein' ? 'desc' : 'asc',
              }))
            }}
          >
            <option value="relevance">Best match</option>
            <option value="time">Fastest</option>
            <option value="calories">Lowest calories</option>
            <option value="protein">Most protein</option>
            <option value="title">Name</option>
          </Select>
          <Button
            aria-label="Toggle sort order"
            variant="secondary"
            size="icon"
            onClick={() =>
              setFilters((value) => ({ ...value, order: value.order === 'asc' ? 'desc' : 'asc' }))
            }
          >
            <ArrowDownAZ className="size-5" />
          </Button>
        </div>
      </div>

      <div className="relative mb-6">
        <Search className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-muted" />
        <Input
          className="h-14 rounded-2xl pl-12 pr-28 text-base shadow-sm"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search recipes, ingredients, or cuisines…"
          aria-label="Search recipes"
        />
        <Button className="absolute right-2 top-2 lg:hidden" variant="secondary" onClick={() => setFiltersOpen(true)}>
          <Filter className="size-4" /> Filters {activeFilters ? `(${activeFilters})` : ''}
        </Button>
      </div>

      <div className="grid gap-7 lg:grid-cols-[minmax(0,230px)_minmax(0,1fr)]">
        <aside className="hidden min-w-0 lg:block">
          <div className="sticky top-8 overflow-hidden rounded-2xl border border-line bg-white p-5 shadow-card">
            <div className="mb-5 flex items-center justify-between gap-2">
              <h2 className="flex min-w-0 items-center gap-2 font-display text-lg font-bold text-ink">
                <SlidersHorizontal className="size-4 shrink-0" /> Filters
              </h2>
              {activeFilters > 0 && (
                <button className="shrink-0 text-xs font-bold text-terracotta" onClick={() => setFilters({ sort: filters.sort, order: filters.order })}>
                  Clear
                </button>
              )}
            </div>
            <FilterFields filters={filters} setFilters={setFilters} cookbooks={cookbookOptions} />
          </div>
        </aside>

        <section className="min-w-0" aria-live="polite">
          <div className="mb-4 flex items-center justify-between">
            <p className="text-sm font-semibold text-muted">
              {recipes.isLoading
                ? 'Finding recipes…'
                : `${items.length}${recipes.hasNextPage ? '+' : ''} recipes`}
            </p>
          </div>
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
                <Button className="mt-5" variant="secondary" onClick={() => { setSearch(''); setFilters({ sort: 'relevance', order: 'asc' }) }}>
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
      </div>

      <Dialog open={filtersOpen} onClose={() => setFiltersOpen(false)} title="Filter recipes">
        <FilterFields filters={filters} setFilters={setFilters} cookbooks={cookbookOptions} />
        <Button className="mt-6 w-full" onClick={() => setFiltersOpen(false)}>Show recipes</Button>
      </Dialog>
    </div>
  )
}
