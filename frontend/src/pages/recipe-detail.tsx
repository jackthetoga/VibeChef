import { useState } from 'react'
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
  UsersRound,
} from 'lucide-react'
import { toast } from 'sonner'
import { pantryApi, recipesApi } from '../lib/api/client'
import { formatMinutes } from '../lib/utils'
import { formatQuantity } from '../lib/units'
import { RecipeArt } from '../components/app-shell'
import { Badge, Button, Card, Skeleton } from '../components/ui'

export function RecipeDetailPage() {
  const { recipeId } = useParams({ strict: false }) as { recipeId?: string }
  const client = useQueryClient()
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const recipe = useQuery({
    queryKey: ['recipe', recipeId],
    queryFn: () => recipesApi.get(recipeId || ''),
    enabled: Boolean(recipeId),
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
      void client.invalidateQueries({ queryKey: ['pantry'] })
      void client.invalidateQueries({ queryKey: ['recipe', recipeId] })
      void client.invalidateQueries({ queryKey: ['recipes'] })
    },
    onError: (error) => toast.error(error.message),
  })

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
    .map((ingredient) => ingredient.name)
    .filter(Boolean)

  return (
    <article className="mx-auto max-w-6xl p-4 sm:p-8 xl:p-10">
      <Link to="/" className="mb-5 inline-flex items-center gap-2 text-sm font-bold text-muted hover:text-ink">
        <ArrowLeft className="size-4" /> Back to recipes
      </Link>
      <div className="grid overflow-hidden rounded-3xl border border-line bg-white shadow-card md:grid-cols-[.85fr_1.15fr]">
        <RecipeArt seed={data.id} className="min-h-72 md:min-h-[430px]" />
        <div className="flex flex-col justify-center p-6 sm:p-10">
          <div className="mb-4 flex flex-wrap gap-2">
            <Badge tone={data.makeable ? 'green' : 'amber'}>
              {data.makeable ? 'Ready from your fridge' : `${data.missing_ingredients || 0} ingredients missing`}
            </Badge>
            {data.cuisine && <Badge>{data.cuisine}</Badge>}
          </div>
          <h1 className="font-display text-4xl font-bold leading-tight tracking-tight text-ink sm:text-5xl">{data.title}</h1>
          {data.cookbook_title && (
            <p className="mt-3 flex items-center gap-2 text-sm font-semibold text-muted">
              <BookOpen className="size-4 text-sage-dark" /> {data.cookbook_title}
              {data.source_page ? ` · p. ${data.source_page}` : ''}
            </p>
          )}
          {data.description && <p className="mt-4 text-base leading-relaxed text-muted">{data.description}</p>}
          <div className="mt-7 grid grid-cols-3 divide-x divide-line rounded-2xl bg-sand p-4 text-center">
            <div><Clock3 className="mx-auto mb-1 size-5 text-sage-dark" /><b className="text-sm text-ink">{formatMinutes(time)}</b><span className="block text-[11px] text-muted">Total time</span></div>
            <div><UsersRound className="mx-auto mb-1 size-5 text-sage-dark" /><b className="text-sm text-ink">{data.servings || '—'}</b><span className="block text-[11px] text-muted">Servings</span></div>
            <div><Flame className="mx-auto mb-1 size-5 text-sage-dark" /><b className="text-sm text-ink">{data.nutrition?.calories ?? '—'}</b><span className="block text-[11px] text-muted">Calories</span></div>
          </div>
          {missingNames.length > 0 && (
            <Button
              className="mt-5 self-start"
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
                  return (
                    <li key={`${ingredient.name}-${index}`}>
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
          </Card>
          {data.nutrition && (
            <Card className="p-5 sm:p-7">
              <h2 className="flex items-center gap-2 font-display text-xl font-bold text-ink"><Gauge className="size-5" /> Nutrition</h2>
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
          <h2 className="flex items-center gap-2 font-display text-2xl font-bold text-ink"><ChefHat className="size-6" /> Let’s cook</h2>
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
    </article>
  )
}
