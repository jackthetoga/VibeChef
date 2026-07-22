import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import {
  ArrowLeft,
  BookOpen,
  Check,
  ChefHat,
  Clock3,
  ExternalLink,
  Flame,
  Gauge,
  Refrigerator,
  Sparkles,
  Star,
  UsersRound,
} from 'lucide-react'
import { toast } from 'sonner'
import { pantryApi, recipesApi, reviewsApi } from '../lib/api/client'
import type { Recipe, RecipeCookItem, RecipeIngredient, RecipeTagUpdate } from '../lib/api/types'
import { cn, formatMinutes } from '../lib/utils'
import { formatQuantity, UNIT_GROUPS } from '../lib/units'
import { RecipeImage } from '../components/app-shell'
import { Badge, Button, Card, Dialog, Field, Input, Select, Skeleton } from '../components/ui'

const TAG_CATEGORIES = [
  '',
  'main dish',
  'side dish',
  'salad',
  'soup',
  'sauce',
  'dessert',
  'breakfast',
  'bread',
  'snack',
  'beverage',
] as const

const TAG_FOOD_GROUPS = [
  { value: 'vegetables', label: 'Vegetables' },
  { value: 'fruits', label: 'Fruits' },
  { value: 'grains', label: 'Grains' },
  { value: 'protein-foods', label: 'Protein Foods' },
  { value: 'dairy', label: 'Dairy' },
] as const

const TAG_CUISINES = [
  '',
  'Italian',
  'Mexican',
  'Mediterranean',
  'Asian',
  'Indian',
  'American',
  'Chinese',
] as const

const TAG_DISH_TAGS = ['pasta', 'seafood', 'stew', 'meat', 'poultry', 'grain', 'vegetable'] as const

const CATEGORY_SET = new Set(TAG_CATEGORIES.filter(Boolean))
const FOOD_GROUP_SET = new Set(TAG_FOOD_GROUPS.map((group) => group.value))
const DISH_TAG_SET = new Set(TAG_DISH_TAGS)

function splitTags(tags: string[] | undefined) {
  let category = ''
  const food_groups: string[] = []
  const dish_tags: string[] = []
  for (const raw of tags || []) {
    const tag = raw.trim().toLowerCase()
    if (!tag) continue
    if (CATEGORY_SET.has(tag as (typeof TAG_CATEGORIES)[number]) && !category) {
      category = tag
      continue
    }
    const group = tag.replace(/ /g, '-')
    if (FOOD_GROUP_SET.has(group as (typeof TAG_FOOD_GROUPS)[number]['value']) && !food_groups.includes(group)) {
      food_groups.push(group)
      continue
    }
    if (tag === 'protein foods' && !food_groups.includes('protein-foods')) {
      food_groups.push('protein-foods')
      continue
    }
    if (DISH_TAG_SET.has(tag as (typeof TAG_DISH_TAGS)[number]) && !dish_tags.includes(tag)) {
      dish_tags.push(tag)
    }
  }
  return { category, food_groups, dish_tags }
}

interface CookDraftRow {
  key: string
  recipeIngredientId?: string
  ingredientId: string
  name: string
  quantity: string
  unit: string
  used: boolean
  matchStatus?: RecipeIngredient['match_status']
  pantryQuantity?: number | null
  pantryUnit?: string | null
  alternates?: NonNullable<RecipeIngredient['alternates']>
  isStaple: boolean
}

function quantityToInput(value?: number | string | null) {
  if (value == null || value === '') return ''
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric)) return String(value)
  return String(numeric)
}

function buildCookDrafts(recipe: Recipe): CookDraftRow[] {
  return (recipe.ingredients || []).map((ingredient, index) => {
    const isStaple = ingredient.match_status === 'staple'
    return {
      key: `${ingredient.ingredient_id || ingredient.id || ingredient.name}-${index}`,
      recipeIngredientId: ingredient.id,
      ingredientId: ingredient.ingredient_id || '',
      name: ingredient.alternates?.length
        ? ingredient.alternates.find((alt) => alt.ingredient_id === ingredient.ingredient_id)?.name ||
          ingredient.alternates[0]?.name ||
          ingredient.name
        : ingredient.name,
      quantity: quantityToInput(ingredient.quantity),
      unit: ingredient.unit || '',
      used: !isStaple,
      matchStatus: ingredient.match_status,
      pantryQuantity: ingredient.pantry_quantity,
      pantryUnit: ingredient.pantry_unit,
      alternates: ingredient.alternates || undefined,
      isStaple,
    }
  }).filter((row) => Boolean(row.ingredientId))
}

function cookToast(result: { updated: unknown[]; removed: string[]; skipped: string[] }) {
  const deducted = result.updated.length + result.removed.length
  if (deducted && result.skipped.length) {
    toast.success(
      `Updated ${deducted} fridge item${deducted === 1 ? '' : 's'} · ${result.skipped.length} not in fridge`,
    )
  } else if (deducted) {
    toast.success(`Subtracted ingredients from your fridge`)
  } else if (result.skipped.length) {
    toast.message('None of those ingredients were in your fridge')
  } else {
    toast.message('Nothing to update in your fridge')
  }
}

function ReviewPhotoImage({
  catalogRecipeId,
  photoId,
  alt,
  className,
}: {
  catalogRecipeId: string
  photoId: string
  alt: string
  className: string
}) {
  const [src, setSrc] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let objectUrl: string | null = null
    void reviewsApi
      .photoBlob(catalogRecipeId, photoId)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setSrc(objectUrl)
      })
      .catch(() => {
        if (!cancelled) setSrc(null)
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [catalogRecipeId, photoId])

  if (!src) return <Skeleton className={className} />
  return <img src={src} alt={alt} className={className} />
}

export function RecipeDetailPage() {
  const { recipeId } = useParams({ strict: false }) as { recipeId?: string }
  const client = useQueryClient()
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [cookOpen, setCookOpen] = useState(false)
  const [cookDrafts, setCookDrafts] = useState<CookDraftRow[]>([])
  const [cookError, setCookError] = useState('')
  const [tagsOpen, setTagsOpen] = useState(false)
  const [tagDraft, setTagDraft] = useState({
    cuisine: '',
    category: '',
    food_groups: [] as string[],
    dish_tags: [] as string[],
  })
  const [reviewRating, setReviewRating] = useState(5)
  const [reviewBody, setReviewBody] = useState('')
  const [reviewError, setReviewError] = useState('')

  const recipe = useQuery({
    queryKey: ['recipe', recipeId],
    queryFn: () => recipesApi.get(recipeId || ''),
    enabled: Boolean(recipeId),
  })

  const catalogRecipeId = recipe.data?.catalog_recipe_id

  const reviews = useQuery({
    queryKey: ['reviews', catalogRecipeId],
    queryFn: () => reviewsApi.list(catalogRecipeId || ''),
    enabled: Boolean(catalogRecipeId),
  })

  const myReview = useQuery({
    queryKey: ['reviews', catalogRecipeId, 'me'],
    queryFn: () => reviewsApi.mine(catalogRecipeId || ''),
    enabled: Boolean(catalogRecipeId),
  })

  const invalidateReviews = () => {
    void client.invalidateQueries({ queryKey: ['reviews', catalogRecipeId] })
    void client.invalidateQueries({ queryKey: ['recipe', recipeId] })
    void client.invalidateQueries({ queryKey: ['recipes'] })
  }

  const saveReview = useMutation({
    mutationFn: async () => {
      if (!catalogRecipeId) throw new Error('This recipe is not linked to the shared catalog yet')
      const input = { rating: reviewRating, body: reviewBody.trim() || null }
      if (myReview.data) return reviewsApi.updateMine(catalogRecipeId, input)
      return reviewsApi.create(catalogRecipeId, input)
    },
    onSuccess: () => {
      setReviewError('')
      toast.success(myReview.data ? 'Review updated' : 'Review posted')
      invalidateReviews()
    },
    onError: (error) => {
      setReviewError(error.message)
      toast.error(error.message)
    },
  })

  const deleteReview = useMutation({
    mutationFn: () => reviewsApi.deleteMine(catalogRecipeId || ''),
    onSuccess: () => {
      setReviewBody('')
      setReviewRating(5)
      toast.success('Review deleted')
      invalidateReviews()
    },
    onError: (error) => toast.error(error.message),
  })

  const uploadReviewPhoto = useMutation({
    mutationFn: (file: File) => reviewsApi.addPhoto(catalogRecipeId || '', file),
    onSuccess: () => {
      toast.success('Photo added')
      invalidateReviews()
    },
    onError: (error) => toast.error(error.message),
  })

  const removeReviewPhoto = useMutation({
    mutationFn: (photoId: string) => reviewsApi.deletePhoto(catalogRecipeId || '', photoId),
    onSuccess: () => {
      toast.success('Photo removed')
      invalidateReviews()
    },
    onError: (error) => toast.error(error.message),
  })

  useEffect(() => {
    if (myReview.data) {
      setReviewRating(myReview.data.rating)
      setReviewBody(myReview.data.body || '')
    } else if (myReview.isSuccess) {
      setReviewRating(5)
      setReviewBody('')
    }
  }, [myReview.data, myReview.isSuccess])

  const invalidateAfterPantryChange = () => {
    void client.invalidateQueries({ queryKey: ['pantry'] })
    void client.invalidateQueries({ queryKey: ['recipe', recipeId] })
    void client.invalidateQueries({ queryKey: ['recipes'] })
  }

  const openTagEditor = () => {
    if (!recipe.data) return
    const parts = splitTags(recipe.data.tags)
    setTagDraft({
      cuisine: recipe.data.cuisine || '',
      category: parts.category,
      food_groups: parts.food_groups,
      dish_tags: parts.dish_tags,
    })
    setTagsOpen(true)
  }

  const saveTags = useMutation({
    mutationFn: (input: RecipeTagUpdate) => recipesApi.update(recipeId || '', input),
    onSuccess: (updated) => {
      client.setQueryData(['recipe', recipeId], updated)
      void client.invalidateQueries({ queryKey: ['recipes'] })
      setTagsOpen(false)
      toast.success('Tags updated')
    },
    onError: (error) => toast.error(error.message),
  })

  const addMissing = useMutation({
    mutationFn: (names: string[]) => pantryApi.createBulk(names.map((name) => ({ name }))),
    onSuccess: (result) => {
      const added = result.added.length
      const skipped = result.skipped_existing.length
      if (added && skipped) {
        toast.success(`Added ${added} to your fridge · ${skipped} already there`)
      } else if (added) {
        toast.success(`Added ${added} ingredient${added === 1 ? '' : 's'} to your fridge`)
      } else {
        toast.message('Those ingredients are already in your fridge')
      }
      invalidateAfterPantryChange()
    },
    onError: (error) => toast.error(error.message),
  })

  const cookRecipe = useMutation({
    mutationFn: (items?: RecipeCookItem[]) => recipesApi.cook(recipeId || '', items),
    onSuccess: (result) => {
      cookToast(result)
      setCookOpen(false)
      setCookError('')
      invalidateAfterPantryChange()
    },
    onError: (error) => {
      setCookError(error.message)
      toast.error(error.message)
    },
  })

  const openCookDialog = () => {
    if (!recipe.data) return
    setCookDrafts(buildCookDrafts(recipe.data))
    setCookError('')
    setCookOpen(true)
  }

  const updateCookDraft = (key: string, patch: Partial<CookDraftRow>) => {
    setCookDrafts((rows) => rows.map((row) => (row.key === key ? { ...row, ...patch } : row)))
  }

  const submitCookReview = (event: React.FormEvent) => {
    event.preventDefault()
    const used = cookDrafts.filter((row) => row.used)
    if (used.length === 0) {
      setCookError('Check at least one ingredient you used, or skip the review.')
      return
    }
    const items: RecipeCookItem[] = []
    for (const row of used) {
      if (row.quantity.trim() === '') {
        items.push({
          ingredient_id: row.ingredientId,
          quantity: null,
          unit: row.unit || null,
        })
        continue
      }
      const quantity = Number(row.quantity)
      if (!Number.isFinite(quantity) || quantity < 0) {
        setCookError(`Enter a valid quantity for ${row.name}`)
        return
      }
      items.push({
        ingredient_id: row.ingredientId,
        quantity,
        unit: row.unit || null,
      })
    }
    setCookError('')
    cookRecipe.mutate(items)
  }

  const skipCookReview = () => {
    setCookError('')
    cookRecipe.mutate(undefined)
  }

  if (!recipeId) {
    return (
      <div className="mx-auto max-w-4xl p-5 sm:p-10">
        <Card className="p-10 text-center">
          <h1 className="font-display text-2xl font-bold text-ink">Recipe unavailable</h1>
          <p className="mt-2 text-muted">No recipe was selected.</p>
          <Link to="/" className="mt-5 inline-flex h-11 items-center rounded-xl bg-ink px-4 text-sm font-semibold text-cream">
            Back to recipes
          </Link>
        </Card>
      </div>
    )
  }

  if (recipe.isLoading) {
    return (
      <div className="mx-auto max-w-6xl p-5 sm:p-10">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="mt-6 aspect-[2/1] w-full rounded-3xl" />
        <Skeleton className="mt-7 h-12 w-3/4" />
      </div>
    )
  }
  if (recipe.isError || !recipe.data) {
    return (
      <div className="mx-auto max-w-4xl p-5 sm:p-10">
        <Card className="p-10 text-center">
          <h1 className="font-display text-2xl font-bold text-ink">Recipe unavailable</h1>
          <p className="mt-2 text-muted">{recipe.error?.message || 'This recipe could not be found.'}</p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <Button onClick={() => void recipe.refetch()}>Try again</Button>
            <Link
              to="/"
              className="inline-flex h-11 items-center rounded-xl border border-line bg-white px-4 text-sm font-semibold text-ink"
            >
              Back to recipes
            </Link>
          </div>
        </Card>
      </div>
    )
  }

  const data = recipe.data
  const time =
    data.total_time_minutes || (data.prep_time_minutes || 0) + (data.cook_time_minutes || 0)
  const missingNames = (data.ingredients || [])
    .filter((ingredient) => ingredient.match_status === 'missing' || ingredient.match_status === 'insufficient')
    .flatMap((ingredient) =>
      ingredient.alternates?.length
        ? ingredient.alternates.map((alternate) => alternate.name)
        : [ingredient.name],
    )
    .filter(Boolean)
  const canCook = (data.ingredients || []).some(
    (ingredient) => ingredient.ingredient_id && ingredient.match_status !== 'staple',
  )
  const tagParts = splitTags(data.tags)

  return (
    <article className="mx-auto max-w-6xl p-4 sm:p-8 xl:p-10">
      <Link to="/" className="mb-5 inline-flex items-center gap-2 text-sm font-bold text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> Back to recipes
      </Link>
      <div className="grid overflow-hidden rounded-3xl border border-line bg-white shadow-card md:grid-cols-[.85fr_1.15fr]">
        <RecipeImage
          recipeId={data.id}
          imageUrl={data.image_url}
          seed={data.id}
          className="min-h-72 md:min-h-[430px]"
        />
        <div className="flex flex-col justify-center p-6 sm:p-10">
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Badge tone={data.makeable ? 'green' : 'amber'}>
              {data.makeable ? 'Ready from your fridge' : `${data.missing_ingredients || 0} ingredients missing`}
            </Badge>
            {data.cuisine && <Badge>{data.cuisine}</Badge>}
            {tagParts.category && <Badge tone="neutral">{tagParts.category}</Badge>}
            {tagParts.food_groups.map((group) => (
              <Badge key={group} tone="neutral">{group.replace('-', ' ')}</Badge>
            ))}
            <button
              type="button"
              className="text-xs font-bold text-sage-dark underline-offset-2 hover:underline"
              onClick={openTagEditor}
            >
              Edit tags
            </button>
          </div>
          <h1 className="font-display text-4xl font-bold leading-tight tracking-tight text-ink sm:text-5xl">{data.title}</h1>
          {data.cookbook_title && (
            <p className="mt-3 flex items-center gap-2 text-sm font-semibold text-muted">
              <BookOpen className="size-4 text-sage-dark" /> {data.cookbook_title}
              {data.source_page ? ` · p. ${data.source_page}` : ''}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-3 text-sm text-muted">
            {data.catalog_recipe_id && (data.user_rating_count ?? 0) > 0 && (
              <span className="inline-flex items-center gap-1 font-semibold text-ink">
                <Star className="size-4 fill-terracotta text-terracotta" />
                {Number(data.user_rating_avg).toFixed(1)} community
                <span className="font-normal text-muted">
                  ({data.user_rating_count} review{(data.user_rating_count || 0) === 1 ? '' : 's'})
                </span>
              </span>
            )}
            {data.rating != null && (
              <span className="inline-flex items-center gap-1">
                Source rating {Number(data.rating).toFixed(1)}
                {data.rating_count != null ? ` · ${data.rating_count}` : ''}
              </span>
            )}
          </div>
          {data.description && <p className="mt-4 text-base leading-relaxed text-muted">{data.description}</p>}
          <div className="mt-7 grid grid-cols-3 divide-x divide-line rounded-2xl bg-sand p-4 text-center">
            <div><Clock3 className="mx-auto mb-1 size-5 text-sage-dark" /><b className="text-sm text-ink">{formatMinutes(time)}</b><span className="block text-[11px] text-muted">Total time</span></div>
            <div><UsersRound className="mx-auto mb-1 size-5 text-sage-dark" /><b className="text-sm text-ink">{data.servings || '—'}</b><span className="block text-[11px] text-muted">Servings</span></div>
            <div>
              <Flame className="mx-auto mb-1 size-5 text-sage-dark" />
              <b className="text-sm text-ink">{data.nutrition?.calories ?? '—'}</b>
              <span className="block text-[11px] text-muted">
                {data.nutrition?.basis === 'whole_recipe' ? 'Calories (recipe)' : 'Calories'}
              </span>
            </div>
          </div>
          <div className="mt-5 flex flex-wrap gap-2">
            {canCook && (
              <Button onClick={openCookDialog}>
                <Sparkles className="size-4" /> I made this
              </Button>
            )}
            {missingNames.length > 0 && (
              <Button
                variant="secondary"
                disabled={addMissing.isPending}
                onClick={() => addMissing.mutate(missingNames)}
              >
                <Refrigerator className="size-4" />
                {addMissing.isPending ? 'Adding…' : `Add ${missingNames.length} missing to fridge`}
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="mt-7 grid gap-7 lg:grid-cols-[.8fr_1.2fr]">
        <div className="grid content-start gap-7">
          <Card className="p-5 sm:p-7">
            <h2 className="font-display text-2xl font-bold text-ink">Ingredients</h2>
            <p className="mt-1 text-sm text-muted">Quantities are compared across compatible units when possible.</p>
            {(data.ingredients || []).length === 0 ? (
              <p className="mt-5 text-sm text-muted">No ingredients were extracted for this recipe.</p>
            ) : (
              <ul className="mt-5 grid gap-2">
                {(data.ingredients || []).map((ingredient, index) => {
                  const inPantry = ingredient.in_pantry ?? false
                  const insufficient = ingredient.match_status === 'insufficient'
                  const prevSection = index > 0 ? (data.ingredients || [])[index - 1]?.section : null
                  const showSection = Boolean(ingredient.section && ingredient.section !== prevSection)
                  return (
                    <li key={`${ingredient.name}-${index}`}>
                      {showSection && (
                        <p className="mb-2 mt-3 text-xs font-semibold uppercase tracking-wide text-muted first:mt-0">
                          {ingredient.section}
                        </p>
                      )}
                      <button
                        className={`flex w-full items-center gap-3 rounded-xl border p-3 text-left transition ${
                          inPantry
                            ? 'border-leaf/25 bg-leaf/8'
                            : insufficient
                              ? 'border-amber-300/60 bg-amber-50'
                              : 'border-line bg-cream'
                        }`}
                        onClick={() =>
                          setChecked((current) => {
                            const next = new Set(current)
                            if (next.has(index)) next.delete(index)
                            else next.add(index)
                            return next
                          })
                        }
                      >
                        <span className={`grid size-5 shrink-0 place-items-center rounded-md border ${
                          checked.has(index) ? 'border-sage bg-sage text-white' : 'border-line bg-white'
                        }`}>
                          {checked.has(index) && <Check className="size-3" />}
                        </span>
                        <span className={`min-w-0 ${checked.has(index) ? 'text-muted line-through' : 'text-ink'}`}>
                          <span className="block">
                            <b>{formatQuantity(ingredient.quantity, ingredient.unit)}</b>{' '}
                            {ingredient.name}
                            {ingredient.preparation ? `, ${ingredient.preparation}` : ''}
                          </span>
                          {insufficient && (
                            <span className="block text-xs text-amber-800">
                              Have {formatQuantity(ingredient.pantry_quantity, ingredient.pantry_unit)}
                            </span>
                          )}
                          {ingredient.matched_via && (
                            <span className="block text-xs text-muted">
                              Matched via {ingredient.matched_via}
                            </span>
                          )}
                          {ingredient.conversion_basis && (
                            <span
                              className="block text-xs text-muted"
                              title={ingredient.conversion_source || undefined}
                            >
                              Approx. using {ingredient.conversion_basis} household weight
                            </span>
                          )}
                        </span>
                        {ingredient.match_status === 'staple' ? (
                          <Badge className="ml-auto" tone="green">Staple</Badge>
                        ) : insufficient ? (
                          <Badge className="ml-auto" tone="amber">Need more</Badge>
                        ) : inPantry ? (
                          <Badge className="ml-auto" tone="green">Have</Badge>
                        ) : null}
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
            {(data.parse_warnings || []).length > 0 && (
              <p className="mt-4 text-xs text-muted">
                Parse notes: {(data.parse_warnings || []).join(' · ')}
              </p>
            )}
          </Card>
          {data.nutrition && (
            <Card className="p-5 sm:p-7">
              <h2 className="flex items-center gap-2 font-display text-xl font-bold text-ink">
                <Gauge className="size-5" /> Nutrition
                {data.nutrition.source === 'estimated' && (
                  <Badge tone="amber">Estimated</Badge>
                )}
                {data.nutrition.source === 'printed' && (
                  <Badge tone="green">From cookbook</Badge>
                )}
              </h2>
              <p className="mt-1 text-sm text-muted">
                {data.nutrition.basis === 'per_serving'
                  ? 'Values are per serving.'
                  : data.nutrition.basis === 'whole_recipe'
                    ? 'Values are for the whole recipe.'
                    : null}
                {data.nutrition.source === 'estimated' && data.nutrition.coverage != null
                  ? ` Coverage ${Math.round(Number(data.nutrition.coverage) * 100)}%.`
                  : null}
              </p>
              <div className="mt-4 grid grid-cols-4 gap-2 text-center">
                {[
                  ['Protein', data.nutrition.protein_g, 'g'],
                  ['Carbs', data.nutrition.carbs_g, 'g'],
                  ['Fat', data.nutrition.fat_g, 'g'],
                  ['Energy', data.nutrition.calories, ''],
                ].map(([label, value, unit]) => (
                  <div key={String(label)} className="rounded-xl bg-sand p-3">
                    <b className="block text-ink">{value ?? '—'}{unit}</b>
                    <span className="text-[11px] text-muted">{label}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>

        <Card className="p-5 sm:p-8">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h2 className="flex items-center gap-2 font-display text-2xl font-bold text-ink">
              <ChefHat className="size-6" /> Let’s cook
            </h2>
            {canCook && (
              <Button size="sm" variant="secondary" onClick={openCookDialog}>
                <Sparkles className="size-3.5" /> I made this
              </Button>
            )}
          </div>
          {(data.steps || []).length === 0 ? (
            <p className="mt-7 text-sm text-muted">No steps were extracted for this recipe.</p>
          ) : (
            <ol className="mt-7 grid gap-7">
              {(data.steps || []).map((step, index) => {
                const text = typeof step === 'string' ? step : step.instruction || step.description
                return (
                  <li key={index} className="grid grid-cols-[40px_1fr] gap-4">
                    <span className="grid size-10 place-items-center rounded-full bg-terracotta font-display text-lg font-bold text-white">{index + 1}</span>
                    <p className="border-b border-line pb-7 leading-7 text-ink">{text}</p>
                  </li>
                )
              })}
            </ol>
          )}
          {(data.source || data.source_url || data.source_page) && (
            <div className="mt-5 rounded-xl bg-sand p-4 text-sm text-muted">
              Source:{' '}
              {data.source_url ? (
                <a className="inline-flex items-center gap-1 font-bold text-sage-dark hover:underline" href={data.source_url} target="_blank" rel="noreferrer">
                  {data.source || 'View original'} <ExternalLink className="size-3" />
                </a>
              ) : <b>{data.source || data.cookbook_title || `Cookbook page ${data.source_page}`}</b>}
            </div>
          )}
        </Card>
      </div>

      {data.catalog_recipe_id ? (
        <Card className="mt-7 p-5 sm:p-8">
          <h2 className="font-display text-2xl font-bold text-ink">Community reviews</h2>
          <p className="mt-1 text-sm text-muted">
            Reviews are shared with everyone who has this same cookbook content. Source ratings stay separate.
          </p>

          <form
            className="mt-6 grid gap-4 rounded-2xl border border-line bg-sand/40 p-4"
            onSubmit={(event) => {
              event.preventDefault()
              if (reviewRating < 1 || reviewRating > 5) {
                setReviewError('Choose a rating from 1 to 5 stars')
                return
              }
              setReviewError('')
              saveReview.mutate()
            }}
          >
            <Field label={myReview.data ? 'Update your review' : 'Write a review'}>
              <div className="flex gap-1">
                {[1, 2, 3, 4, 5].map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-label={`${value} star${value === 1 ? '' : 's'}`}
                    className="rounded-md p-1 text-terracotta transition hover:bg-white"
                    onClick={() => setReviewRating(value)}
                  >
                    <Star
                      className={cn(
                        'size-6',
                        value <= reviewRating ? 'fill-terracotta text-terracotta' : 'text-line',
                      )}
                    />
                  </button>
                ))}
              </div>
            </Field>
            <Field label="Comments" hint="Optional">
              <textarea
                className="min-h-24 w-full rounded-xl border border-line bg-white px-3 py-2 text-sm font-normal text-ink outline-none ring-sage/30 focus:ring-2"
                value={reviewBody}
                onChange={(event) => setReviewBody(event.target.value)}
                maxLength={5000}
                placeholder="How did it turn out?"
              />
            </Field>
            {myReview.data ? (
              <div className="flex flex-wrap gap-3">
                {(myReview.data.photos || []).map((photo) => (
                  <div key={photo.id} className="relative">
                    <ReviewPhotoImage
                      catalogRecipeId={data.catalog_recipe_id!}
                      photoId={photo.id}
                      alt="Your review"
                      className="size-20 rounded-xl object-cover"
                    />
                    <button
                      type="button"
                      className="absolute -right-1 -top-1 rounded-full bg-ink px-1.5 text-xs text-white"
                      onClick={() => removeReviewPhoto.mutate(photo.id)}
                    >
                      ×
                    </button>
                  </div>
                ))}
                {(myReview.data.photos?.length || 0) < 5 && (
                  <label className="grid size-20 cursor-pointer place-items-center rounded-xl border border-dashed border-line bg-white text-xs font-semibold text-muted">
                    Add photo
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      className="hidden"
                      onChange={(event) => {
                        const file = event.target.files?.[0]
                        if (file) uploadReviewPhoto.mutate(file)
                        event.target.value = ''
                      }}
                    />
                  </label>
                )}
              </div>
            ) : (
              <p className="text-xs text-muted">Post your review first, then you can add photos.</p>
            )}
            {reviewError && <p className="text-sm text-terracotta">{reviewError}</p>}
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={saveReview.isPending}>
                {saveReview.isPending ? 'Saving…' : myReview.data ? 'Update review' : 'Post review'}
              </Button>
              {myReview.data && (
                <Button
                  type="button"
                  variant="secondary"
                  disabled={deleteReview.isPending}
                  onClick={() => deleteReview.mutate()}
                >
                  Delete review
                </Button>
              )}
            </div>
          </form>

          <div className="mt-8 grid gap-4">
            {reviews.isLoading && <Skeleton className="h-24 w-full" />}
            {(reviews.data?.items || []).length === 0 && !reviews.isLoading && (
              <p className="text-sm text-muted">No community reviews yet.</p>
            )}
            {(reviews.data?.items || []).map((review) => (
              <div key={review.id} className="rounded-2xl border border-line bg-white p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <div className="flex">
                      {[1, 2, 3, 4, 5].map((value) => (
                        <Star
                          key={value}
                          className={cn(
                            'size-4',
                            value <= review.rating ? 'fill-terracotta text-terracotta' : 'text-line',
                          )}
                        />
                      ))}
                    </div>
                    <b className="text-sm text-ink">{review.display_name || 'Cook'}</b>
                  </div>
                  <span className="text-xs text-muted">
                    {new Date(review.created_at).toLocaleDateString()}
                  </span>
                </div>
                {review.body && <p className="mt-2 text-sm leading-relaxed text-ink">{review.body}</p>}
                {review.photos?.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {review.photos.map((photo) => (
                      <ReviewPhotoImage
                        key={photo.id}
                        catalogRecipeId={data.catalog_recipe_id!}
                        photoId={photo.id}
                        alt=""
                        className="size-24 rounded-xl object-cover"
                      />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <Card className="mt-7 p-5 sm:p-8">
          <h2 className="font-display text-2xl font-bold text-ink">Community reviews</h2>
          <p className="mt-2 text-sm text-muted">
            Reviews will be available once this recipe is linked to the shared catalog.
          </p>
        </Card>
      )}

      <Dialog
        open={cookOpen}
        onClose={() => {
          if (cookRecipe.isPending) return
          setCookOpen(false)
          setCookError('')
        }}
        title="I made this"
        className="sm:max-w-2xl"
      >
        <form className="grid gap-4" onSubmit={submitCookReview}>
          <p className="text-sm text-muted">
            Check what you used and tweak amounts if needed. We’ll subtract those from your fridge.
          </p>
          {cookDrafts.length === 0 ? (
            <p className="text-sm text-muted">This recipe has no ingredients to subtract.</p>
          ) : (
            <div className="max-h-[50vh] space-y-3 overflow-auto pr-1">
              {cookDrafts.map((row) => {
                const selectedAlternate = row.alternates?.find(
                  (alt) => alt.ingredient_id === row.ingredientId,
                )
                return (
                  <div
                    key={row.key}
                    className={`rounded-2xl border p-3 transition ${
                      row.used ? 'border-line bg-white' : 'border-line/70 bg-sand/60 opacity-70'
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <button
                        type="button"
                        aria-pressed={row.used}
                        aria-label={`${row.used ? 'Uncheck' : 'Check'} ${row.name}`}
                        className={`mt-1 grid size-5 shrink-0 place-items-center rounded-md border ${
                          row.used ? 'border-sage bg-sage text-white' : 'border-line bg-white'
                        }`}
                        onClick={() => updateCookDraft(row.key, { used: !row.used })}
                      >
                        {row.used && <Check className="size-3" />}
                      </button>
                      <div className="min-w-0 flex-1 grid gap-2">
                        {row.alternates && row.alternates.length > 1 ? (
                          <Field label="Used">
                            <Select
                              disabled={!row.used}
                              value={row.ingredientId}
                              onChange={(event) => {
                                const alternate = row.alternates?.find(
                                  (alt) => alt.ingredient_id === event.target.value,
                                )
                                updateCookDraft(row.key, {
                                  ingredientId: event.target.value,
                                  name: alternate?.name || row.name,
                                  quantity: quantityToInput(
                                    alternate?.quantity ?? (selectedAlternate?.quantity ?? row.quantity),
                                  ),
                                  unit: alternate?.unit || row.unit,
                                })
                              }}
                            >
                              {row.alternates.map((alternate) => (
                                <option
                                  key={alternate.ingredient_id || alternate.name}
                                  value={alternate.ingredient_id || ''}
                                >
                                  {alternate.name}
                                </option>
                              ))}
                            </Select>
                          </Field>
                        ) : (
                          <p className="text-sm font-semibold text-ink">
                            {row.name}
                            {row.isStaple && (
                              <Badge className="ml-2" tone="green">Staple</Badge>
                            )}
                          </p>
                        )}
                        <div className="grid grid-cols-2 gap-2">
                          <Field label="Quantity">
                            <Input
                              min="0"
                              step="any"
                              type="number"
                              disabled={!row.used}
                              placeholder="Amount"
                              value={row.quantity}
                              onChange={(event) =>
                                updateCookDraft(row.key, { quantity: event.target.value })
                              }
                            />
                          </Field>
                          <Field label="Unit">
                            <Select
                              disabled={!row.used}
                              value={row.unit}
                              onChange={(event) =>
                                updateCookDraft(row.key, { unit: event.target.value })
                              }
                            >
                              <option value="">None</option>
                              {row.unit &&
                                !UNIT_GROUPS.some((group) =>
                                  group.units.some(([value]) => value === row.unit),
                                ) && <option value={row.unit}>{row.unit}</option>}
                              {UNIT_GROUPS.map((group) => (
                                <optgroup key={group.label} label={group.label}>
                                  {group.units.map(([value, label]) => (
                                    <option key={value} value={value}>{label}</option>
                                  ))}
                                </optgroup>
                              ))}
                            </Select>
                          </Field>
                        </div>
                        {row.matchStatus === 'missing' && (
                          <p className="text-xs font-semibold text-muted">Not currently in your fridge</p>
                        )}
                        {row.matchStatus === 'insufficient' && (
                          <p className="text-xs font-semibold text-amber-800">
                            Fridge has {formatQuantity(row.pantryQuantity, row.pantryUnit)}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
          {cookError && <p role="alert" className="text-sm font-semibold text-rose-700">{cookError}</p>}
          <div className="grid gap-2 sm:grid-cols-2">
            <Button
              type="button"
              variant="secondary"
              disabled={cookRecipe.isPending || !canCook}
              onClick={skipCookReview}
            >
              Skip review
            </Button>
            <Button type="submit" disabled={cookRecipe.isPending || cookDrafts.every((row) => !row.used)}>
              {cookRecipe.isPending ? 'Updating…' : 'Update fridge'}
            </Button>
          </div>
          <p className="text-xs text-muted">
            Skip review uses the recipe’s default amounts for non-staple ingredients.
          </p>
        </form>
      </Dialog>

      <Dialog
        open={tagsOpen}
        onClose={() => {
          if (saveTags.isPending) return
          setTagsOpen(false)
        }}
        title="Edit tags"
        className="sm:max-w-lg"
      >
        <form
          className="grid gap-5"
          onSubmit={(event) => {
            event.preventDefault()
            saveTags.mutate({
              cuisine: tagDraft.cuisine || null,
              category: tagDraft.category || null,
              food_groups: tagDraft.food_groups,
              dish_tags: tagDraft.dish_tags,
            })
          }}
        >
          <p className="text-sm text-muted">
            Category, food groups, and dish tags stack in filters. Cuisine is exclusive — only one at a time.
          </p>
          <Field label="Category">
            <Select
              value={tagDraft.category}
              onChange={(event) => setTagDraft((current) => ({ ...current, category: event.target.value }))}
            >
              <option value="">No category</option>
              {TAG_CATEGORIES.filter(Boolean).map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Cuisine">
            <Select
              value={tagDraft.cuisine}
              onChange={(event) => setTagDraft((current) => ({ ...current, cuisine: event.target.value }))}
            >
              <option value="">No cuisine</option>
              {TAG_CUISINES.filter(Boolean).map((cuisine) => (
                <option key={cuisine} value={cuisine}>
                  {cuisine}
                </option>
              ))}
            </Select>
          </Field>
          <div>
            <p className="mb-2 text-sm font-bold text-ink">Food groups</p>
            <div className="flex flex-wrap gap-2">
              {TAG_FOOD_GROUPS.map((group) => {
                const active = tagDraft.food_groups.includes(group.value)
                return (
                  <button
                    key={group.value}
                    type="button"
                    aria-pressed={active}
                    className={cn(
                      'rounded-full border px-3 py-1.5 text-sm font-semibold transition',
                      active ? 'border-ink bg-ink text-cream' : 'border-line bg-white text-ink hover:bg-sand',
                    )}
                    onClick={() =>
                      setTagDraft((current) => ({
                        ...current,
                        food_groups: active
                          ? current.food_groups.filter((value) => value !== group.value)
                          : [...current.food_groups, group.value],
                      }))
                    }
                  >
                    {group.label}
                  </button>
                )
              })}
            </div>
          </div>
          <div>
            <p className="mb-2 text-sm font-bold text-ink">Dish tags</p>
            <div className="flex flex-wrap gap-2">
              {TAG_DISH_TAGS.map((dish) => {
                const active = tagDraft.dish_tags.includes(dish)
                return (
                  <button
                    key={dish}
                    type="button"
                    aria-pressed={active}
                    className={cn(
                      'rounded-full border px-3 py-1.5 text-sm font-semibold capitalize transition',
                      active ? 'border-ink bg-ink text-cream' : 'border-line bg-white text-ink hover:bg-sand',
                    )}
                    onClick={() =>
                      setTagDraft((current) => ({
                        ...current,
                        dish_tags: active
                          ? current.dish_tags.filter((value) => value !== dish)
                          : [...current.dish_tags, dish],
                      }))
                    }
                  >
                    {dish}
                  </button>
                )
              })}
            </div>
          </div>
          <Button type="submit" disabled={saveTags.isPending}>
            {saveTags.isPending ? 'Saving…' : 'Save tags'}
          </Button>
        </form>
      </Dialog>
    </article>
  )
}
