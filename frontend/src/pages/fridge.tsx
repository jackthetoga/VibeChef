import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  CalendarDays,
  Camera,
  Check,
  ChefHat,
  NotebookPen,
  Pencil,
  Plus,
  Receipt,
  Refrigerator,
  Search,
  Sparkles,
  Trash2,
  Wheat,
} from 'lucide-react'
import { toast } from 'sonner'
import { ingredientsApi, pantryApi } from '../lib/api/client'
import type {
  CursorPage,
  Ingredient,
  IngredientUnlockSet,
  PantryBulkItem,
  PantryConfirmItem,
  PantryConfirmResult,
  PantryFromTextResult,
  PantryInput,
  PantryItem,
  PantryScanItem,
  UnlockSetIngredient,
} from '../lib/api/types'
import { formatDate, useDebouncedValue } from '../lib/utils'
import { formatQuantity, UNIT_GROUPS } from '../lib/units'
import { Badge, Button, Card, Dialog, Field, Input, Select, Skeleton } from '../components/ui'

type ScanDraftRow = {
  key: string
  name: string
  quantity: string
  unit: string
}

type ScanMode = 'grocery' | 'receipt'

function itemName(item: PantryItem) {
  return item.ingredient?.name || item.ingredient_name || item.name || 'Ingredient'
}

function newDraftKey() {
  return `draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function draftsFromScan(items: PantryScanItem[]): ScanDraftRow[] {
  return items.map((item) => ({
    key: newDraftKey(),
    name: item.name,
    quantity: item.quantity == null ? '' : String(item.quantity),
    unit: item.unit || '',
  }))
}

/** iPhone photos often arrive as HEIC/HEIF with an empty MIME type in some browsers. */
function isSupportedPhoto(file: File) {
  if (file.type.startsWith('image/')) return true
  return /\.(jpe?g|png|webp|heic|heif)$/i.test(file.name)
}

function expiryState(value?: string | null) {
  if (!value) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const expiry = new Date(`${value.slice(0, 10)}T00:00:00`)
  const days = Math.ceil((expiry.getTime() - today.getTime()) / 86_400_000)
  if (days < 0) return { label: 'Expired', tone: 'rose' as const }
  if (days === 0) return { label: 'Use today', tone: 'amber' as const }
  if (days <= 3) return { label: `${days}d left`, tone: 'amber' as const }
  return null
}

export function FridgePage() {
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [preferredCategory, setPreferredCategory] = useState<string | null>(null)
  const [quickOpen, setQuickOpen] = useState(false)
  const [textOpen, setTextOpen] = useState(false)
  const [inventoryText, setInventoryText] = useState('')
  const [textError, setTextError] = useState('')
  const [scanOpen, setScanOpen] = useState(false)
  const [scanMode, setScanMode] = useState<ScanMode>('grocery')
  const [scanDrafts, setScanDrafts] = useState<ScanDraftRow[]>([])
  const [scanError, setScanError] = useState('')
  const scanInputRef = useRef<HTMLInputElement>(null)
  const receiptInputRef = useRef<HTMLInputElement>(null)
  const [ingredientQuery, setIngredientQuery] = useState('')
  const [selected, setSelected] = useState<Ingredient | null>(null)
  const [quantity, setQuantity] = useState('')
  const [unit, setUnit] = useState('')
  const [expiry, setExpiry] = useState('')
  const [formError, setFormError] = useState('')
  const [pantryQuery, setPantryQuery] = useState('')
  const [commonQuery, setCommonQuery] = useState('')
  const [selectedCommon, setSelectedCommon] = useState<Set<string>>(new Set())
  const [commonQuantities, setCommonQuantities] = useState<Record<string, string>>({})
  const [commonUnits, setCommonUnits] = useState<Record<string, string>>({})
  const [editing, setEditing] = useState<PantryItem | null>(null)
  const [editQuantity, setEditQuantity] = useState('')
  const [editUnit, setEditUnit] = useState('')
  const [editExpiry, setEditExpiry] = useState('')
  const [editError, setEditError] = useState('')
  const [unlockSize, setUnlockSize] = useState<1 | 2 | 3>(1)
  const debouncedIngredient = useDebouncedValue(ingredientQuery.trim(), 250)

  const pantry = useQuery({ queryKey: ['pantry'], queryFn: pantryApi.list })
  const unlocks = useQuery({
    queryKey: ['pantry', 'unlock-sets', unlockSize],
    queryFn: () => pantryApi.unlockSets(unlockSize, 10),
  })
  const commonIngredients = useQuery({
    queryKey: ['ingredients', 'common'],
    queryFn: ingredientsApi.common,
    enabled: quickOpen,
  })
  const ingredients = useQuery({
    queryKey: ['ingredients', debouncedIngredient],
    queryFn: () => ingredientsApi.search(debouncedIngredient),
    enabled: debouncedIngredient.length >= 2,
  })

  const addItem = useMutation({
    mutationFn: (input: PantryInput) => pantryApi.create(input),
    onMutate: async (input) => {
      await client.cancelQueries({ queryKey: ['pantry'] })
      const previous = client.getQueryData<CursorPage<PantryItem>>(['pantry'])
      const optimistic: PantryItem = {
        id: `optimistic-${Date.now()}`,
        ingredient_id: input.ingredient_id,
        ingredient_name: input.ingredient_name,
        quantity: input.quantity,
        unit: input.unit,
        expires_at: input.expires_at,
      }
      client.setQueryData<CursorPage<PantryItem>>(['pantry'], (current) => ({
        ...(current || { items: [] }),
        items: [optimistic, ...(current?.items || [])],
      }))
      return { previous }
    },
    onError: (error, _input, context) => {
      client.setQueryData(['pantry'], context?.previous)
      toast.error(error.message)
    },
    onSuccess: () => {
      toast.success('Added to your fridge')
      setOpen(false)
      setPreferredCategory(null)
      setIngredientQuery('')
      setSelected(null)
      setQuantity('')
      setUnit('')
      setExpiry('')
      setFormError('')
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['pantry'] })
      void client.invalidateQueries({ queryKey: ['recipes'] })
      void client.invalidateQueries({ queryKey: ['recipe'] })
    },
  })

  const removeItem = useMutation({
    mutationFn: pantryApi.remove,
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: ['pantry'] })
      const previous = client.getQueryData<CursorPage<PantryItem>>(['pantry'])
      client.setQueryData<CursorPage<PantryItem>>(['pantry'], (current) =>
        current ? { ...current, items: current.items.filter((item) => item.id !== id) } : current,
      )
      return { previous }
    },
    onError: (error, _id, context) => {
      client.setQueryData(['pantry'], context?.previous)
      toast.error(error.message)
    },
    onSuccess: () => {
      toast.success('Ingredient removed')
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['pantry'] })
      void client.invalidateQueries({ queryKey: ['recipes'] })
      void client.invalidateQueries({ queryKey: ['recipe'] })
    },
  })

  const addCommon = useMutation({
    mutationFn: (items: PantryBulkItem[]) => pantryApi.createBulk(items),
    onError: (error) => toast.error(error.message),
    onSuccess: (result) => {
      toast.success(
        result.added.length === 1
          ? 'Added 1 pantry staple'
          : `Added ${result.added.length} pantry staples`,
      )
      setQuickOpen(false)
      setSelectedCommon(new Set())
      setCommonQuantities({})
      setCommonUnits({})
      setCommonQuery('')
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['pantry'] })
      void client.invalidateQueries({ queryKey: ['recipes'] })
      void client.invalidateQueries({ queryKey: ['recipe'] })
    },
  })

  const addUnlockSet = useMutation({
    mutationFn: ({
      items,
    }: {
      set: IngredientUnlockSet
      items: PantryBulkItem[]
    }) => pantryApi.createBulk(items),
    onError: (error) => toast.error(error.message),
    onSuccess: (result, variables) => {
      toast.success(
        result.added.length === 1
          ? 'Added 1 recommended ingredient'
          : `Added ${result.added.length} recommended ingredients`,
      )
      const topUp = variables.set.ingredients.find(
        (ingredient) => ingredient.status === 'insufficient',
      )
      if (topUp) openUnlockSuggestion(topUp)
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['pantry'] })
      void client.invalidateQueries({ queryKey: ['recipes'] })
      void client.invalidateQueries({ queryKey: ['recipe'] })
    },
  })

  const updateItem = useMutation({
    mutationFn: ({ id, input }: { id: string; input: Partial<PantryInput> }) =>
      pantryApi.update(id, input),
    onError: (error) => toast.error(error.message),
    onSuccess: () => {
      toast.success('Ingredient updated')
      setEditing(null)
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['pantry'] })
      void client.invalidateQueries({ queryKey: ['recipes'] })
      void client.invalidateQueries({ queryKey: ['recipe'] })
    },
  })

  const applyTextUpdate = useMutation({
    mutationFn: (text: string) => pantryApi.fromText(text),
    onError: (error) => {
      setTextError(error.message)
      toast.error(error.message)
    },
    onSuccess: (result: PantryFromTextResult) => {
      const parts: string[] = []
      if (result.added.length) {
        parts.push(`added ${result.added.length}`)
      }
      if (result.updated.length) {
        parts.push(`updated ${result.updated.length}`)
      }
      if (result.removed.length) {
        parts.push(`removed ${result.removed.length}`)
      }
      toast.success(
        parts.length
          ? `Fridge ${parts.join(', ')}`
          : result.skipped.length
            ? 'No fridge changes — some removals were not found'
            : 'No fridge changes',
      )
      if (result.skipped.length) {
        toast.message(`Skipped: ${result.skipped.join(', ')}`)
      }
      setTextOpen(false)
      setInventoryText('')
      setTextError('')
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['pantry'] })
      void client.invalidateQueries({ queryKey: ['recipes'] })
      void client.invalidateQueries({ queryKey: ['recipe'] })
    },
  })

  const scanPhoto = useMutation({
    mutationFn: (file: File) => pantryApi.scan(file),
    onError: (error) => {
      toast.error(error.message)
    },
    onSuccess: (result) => {
      if (!result.items.length) {
        toast.error('No groceries detected. Try a clearer photo.')
        return
      }
      setScanMode('grocery')
      setScanDrafts(draftsFromScan(result.items))
      setScanError('')
      setScanOpen(true)
    },
  })

  const scanReceipt = useMutation({
    mutationFn: (file: File) => pantryApi.scanReceipt(file),
    onError: (error) => {
      toast.error(error.message)
    },
    onSuccess: (result) => {
      if (!result.items.length) {
        toast.error('No receipt items detected. Try a clearer photo.')
        return
      }
      setScanMode('receipt')
      setScanDrafts(draftsFromScan(result.items))
      setScanError('')
      setScanOpen(true)
    },
  })

  const confirmScan = useMutation({
    mutationFn: (items: PantryConfirmItem[]) =>
      scanMode === 'receipt'
        ? pantryApi.confirmReceipt(items)
        : pantryApi.confirm(items),
    onError: (error) => {
      setScanError(error.message)
      toast.error(error.message)
    },
    onSuccess: (result: PantryConfirmResult) => {
      const parts: string[] = []
      if (result.added.length) parts.push(`added ${result.added.length}`)
      if (result.updated.length) parts.push(`updated ${result.updated.length}`)
      toast.success(parts.length ? `Fridge ${parts.join(', ')}` : 'No fridge changes')
      setScanOpen(false)
      setScanDrafts([])
      setScanError('')
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['pantry'] })
      void client.invalidateQueries({ queryKey: ['recipes'] })
      void client.invalidateQueries({ queryKey: ['recipe'] })
    },
  })

  const groups = useMemo(() => {
    const search = pantryQuery.trim().toLowerCase()
    return (pantry.data?.items || []).filter((item) => (
      !search || itemName(item).toLowerCase().includes(search)
    )).reduce<Record<string, PantryItem[]>>((result, item) => {
      const category = item.ingredient?.category || item.category || 'Other'
      ;(result[category] ||= []).push(item)
      return result
    }, {})
  }, [pantry.data, pantryQuery])

  const pantryNames = useMemo(
    () => new Set((pantry.data?.items || []).map((item) => itemName(item).toLowerCase())),
    [pantry.data],
  )
  const filteredCommon = useMemo(() => {
    const search = commonQuery.trim().toLowerCase()
    return (commonIngredients.data || []).filter((item) =>
      !search || item.name.includes(search) || item.category.toLowerCase().includes(search),
    )
  }, [commonIngredients.data, commonQuery])

  const submitCommon = () => {
    const items: PantryBulkItem[] = []
    for (const name of selectedCommon) {
      const quantityValue = commonQuantities[name]?.trim()
      const unitValue = commonUnits[name]?.trim()
      if (!quantityValue && !unitValue) {
        items.push({ name })
        continue
      }
      const parsedQuantity = quantityValue ? Number(quantityValue) : null
      if (parsedQuantity !== null && (!Number.isFinite(parsedQuantity) || parsedQuantity < 0)) {
        toast.error(`Quantity for ${name} must be a non-negative number.`)
        return
      }
      items.push({
        name,
        quantity: parsedQuantity,
        unit: unitValue || null,
      })
    }
    addCommon.mutate(items)
  }

  const startEditing = (item: PantryItem) => {
    setEditing(item)
    setEditQuantity(item.quantity == null ? '' : String(item.quantity))
    setEditUnit(item.unit || '')
    setEditExpiry((item.expires_at || item.expiry_date || '').slice(0, 10))
    setEditError('')
  }

  const openUnlockSuggestion = (suggestion: UnlockSetIngredient) => {
    if (suggestion.status === 'insufficient' && suggestion.pantry_item_id) {
      const pantryItem = pantry.data?.items.find((item) => item.id === suggestion.pantry_item_id)
      if (pantryItem) {
        startEditing(pantryItem)
        return
      }
    }
    setSelected({
      id: suggestion.ingredient_id,
      name: suggestion.name,
      category: suggestion.category,
    })
    setIngredientQuery(suggestion.name)
    setPreferredCategory(suggestion.category || null)
    setFormError('')
    setOpen(true)
  }

  const applyUnlockSet = (set: IngredientUnlockSet) => {
    const missing = set.ingredients
      .filter((ingredient) => ingredient.status === 'missing')
      .map((ingredient) => ({ name: ingredient.name }))
    if (missing.length) {
      addUnlockSet.mutate({ set, items: missing })
      return
    }
    const topUp = set.ingredients.find((ingredient) => ingredient.status === 'insufficient')
    if (topUp) openUnlockSuggestion(topUp)
  }

  const openAddDialog = (category?: string | null) => {
    setPreferredCategory(category && category !== 'Other' ? category : null)
    setFormError('')
    setOpen(true)
  }

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (!selected && !ingredientQuery.trim()) return
    const parsedQuantity = quantity ? Number(quantity) : null
    if (parsedQuantity !== null && (!Number.isFinite(parsedQuantity) || parsedQuantity < 0)) {
      setFormError('Quantity must be a non-negative number.')
      return
    }
    setFormError('')
    addItem.mutate({
      ingredient_id: selected?.id,
      ingredient_name: selected ? undefined : ingredientQuery.trim(),
      category: preferredCategory || undefined,
      quantity: parsedQuantity,
      unit: unit || null,
      expires_at: expiry || null,
    })
  }

  const submitEdit = (event: React.FormEvent) => {
    event.preventDefault()
    if (!editing) return
    const parsedQuantity = editQuantity ? Number(editQuantity) : null
    if (parsedQuantity !== null && (!Number.isFinite(parsedQuantity) || parsedQuantity < 0)) {
      setEditError('Quantity must be a non-negative number.')
      return
    }
    setEditError('')
    updateItem.mutate({
      id: editing.id,
      input: {
        quantity: parsedQuantity,
        unit: editUnit || null,
        expires_at: editExpiry || null,
      },
    })
  }

  const submitTextUpdate = (event: React.FormEvent) => {
    event.preventDefault()
    const trimmed = inventoryText.trim()
    if (!trimmed) {
      setTextError('Describe what you added or used.')
      return
    }
    setTextError('')
    applyTextUpdate.mutate(trimmed)
  }

  const onScanFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!isSupportedPhoto(file)) {
      toast.error('Please choose a photo (JPEG, PNG, WebP, HEIC, or HEIF).')
      return
    }
    scanPhoto.mutate(file)
  }

  const onReceiptFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!isSupportedPhoto(file)) {
      toast.error('Please choose a photo (JPEG, PNG, WebP, HEIC, or HEIF).')
      return
    }
    scanReceipt.mutate(file)
  }

  const updateScanDraft = (key: string, patch: Partial<ScanDraftRow>) => {
    setScanDrafts((current) =>
      current.map((row) => (row.key === key ? { ...row, ...patch } : row)),
    )
  }

  const removeScanDraft = (key: string) => {
    setScanDrafts((current) => current.filter((row) => row.key !== key))
  }

  const addScanDraft = () => {
    setScanDrafts((current) => [
      ...current,
      { key: newDraftKey(), name: '', quantity: '', unit: '' },
    ])
  }

  const submitScanConfirm = (event: React.FormEvent) => {
    event.preventDefault()
    const items: PantryConfirmItem[] = []
    for (const row of scanDrafts) {
      const name = row.name.trim()
      if (!name) {
        setScanError('Every row needs an ingredient name, or remove the empty row.')
        return
      }
      const quantityValue = row.quantity.trim()
      const parsedQuantity = quantityValue ? Number(quantityValue) : null
      if (parsedQuantity !== null && (!Number.isFinite(parsedQuantity) || parsedQuantity < 0)) {
        setScanError(`Quantity for ${name} must be a non-negative number.`)
        return
      }
      items.push({
        ingredient_name: name,
        quantity: parsedQuantity,
        unit: row.unit.trim() || null,
      })
    }
    if (!items.length) {
      setScanError('Add at least one ingredient before confirming.')
      return
    }
    setScanError('')
    confirmScan.mutate(items)
  }

  return (
    <div className="mx-auto max-w-6xl p-4 sm:p-8 xl:p-10">
      <input
        ref={scanInputRef}
        type="file"
        accept="image/*,.heic,.heif,image/heic,image/heif"
        capture="environment"
        className="sr-only"
        aria-hidden
        tabIndex={-1}
        onChange={onScanFileChange}
      />
      <input
        ref={receiptInputRef}
        type="file"
        accept="image/*,.heic,.heif,image/heic,image/heif"
        capture="environment"
        className="sr-only"
        aria-hidden
        tabIndex={-1}
        onChange={onReceiptFileChange}
      />
      <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
        <div>
          <p className="mb-2 text-xs font-bold uppercase tracking-[.18em] text-terracotta">Your ingredients</p>
          <h1 className="font-display text-4xl font-bold text-ink sm:text-5xl">What’s in the fridge?</h1>
          <p className="mt-2 text-muted">Keep this fresh and we’ll find better recipe matches.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            size="lg"
            disabled={scanPhoto.isPending || scanReceipt.isPending}
            onClick={() => scanInputRef.current?.click()}
          >
            <Camera className="size-5" />
            {scanPhoto.isPending ? 'Scanning…' : 'Scan groceries'}
          </Button>
          <Button
            variant="secondary"
            size="lg"
            disabled={scanPhoto.isPending || scanReceipt.isPending}
            onClick={() => receiptInputRef.current?.click()}
          >
            <Receipt className="size-5" />
            {scanReceipt.isPending ? 'Scanning…' : 'Scan receipt'}
          </Button>
          <Button variant="secondary" size="lg" onClick={() => setTextOpen(true)}>
            <NotebookPen className="size-5" /> Update from notes
          </Button>
          <Button variant="secondary" size="lg" onClick={() => setQuickOpen(true)}>
            <Sparkles className="size-5" /> Quick add staples
          </Button>
          <Button size="lg" onClick={() => openAddDialog()}>
            <Plus className="size-5" /> Add ingredient
          </Button>
        </div>
      </div>

      <Card className="mt-8 overflow-hidden border-0 bg-gradient-to-r from-sage-dark to-sage p-6 text-white">
        <div className="flex items-center gap-4">
          <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-white/15"><Refrigerator className="size-6" /></span>
          <div>
            <b className="font-display text-xl">{pantry.data?.items.length || 0} ingredients ready</b>
            <p className="mt-1 text-sm text-white/75">Your pantry powers makeable recipe suggestions.</p>
          </div>
        </div>
      </Card>

      <Card className="mt-6 overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-line bg-sand/50 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-leaf/12 text-leaf-dark">
              <ChefHat className="size-5" />
            </span>
            <div>
              <h2 className="font-display text-xl font-bold text-ink">Unlock more recipes</h2>
              <p className="text-sm text-muted">Best ingredients to add from your enabled cookbooks.</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-xl border border-line bg-white p-1">
              {([1, 2, 3] as const).map((size) => (
                <button
                  key={size}
                  type="button"
                  aria-pressed={unlockSize === size}
                  className={`rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                    unlockSize === size ? 'bg-sage text-white' : 'text-muted hover:bg-sand'
                  }`}
                  onClick={() => setUnlockSize(size)}
                >
                  {size} item{size === 1 ? '' : 's'}
                </button>
              ))}
            </div>
            {unlocks.data?.items.length ? (
              <Badge tone="green">{unlocks.data.items.length} suggestions</Badge>
            ) : null}
          </div>
        </div>
        {unlocks.isLoading ? (
          <div className="grid gap-3 p-5">
            {[1, 2, 3].map((item) => <Skeleton key={item} className="h-16 rounded-xl" />)}
          </div>
        ) : unlocks.isError ? (
          <div className="p-5 text-sm text-muted">
            Suggestions didn’t load.{' '}
            <button className="font-bold text-sage-dark hover:underline" onClick={() => void unlocks.refetch()}>
              Try again
            </button>
          </div>
        ) : unlocks.data?.items.length ? (
          <div>
            <ol className="divide-y divide-line">
              {unlocks.data.items.map((set, index) => (
                <li
                  key={set.ingredients.map((ingredient) => ingredient.ingredient_id).join(':')}
                  className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:px-5"
                >
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-sand text-sm font-bold text-muted">
                    {index + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      {set.ingredients.map((ingredient, ingredientIndex) => (
                        <span key={ingredient.ingredient_id} className="contents">
                          {ingredientIndex > 0 && <span className="font-bold text-muted">+</span>}
                          <button
                            type="button"
                            className="font-bold capitalize text-ink hover:text-sage-dark hover:underline"
                            onClick={() => openUnlockSuggestion(ingredient)}
                          >
                            {ingredient.name}
                          </button>
                          {ingredient.status === 'insufficient' && (
                            <Badge tone="amber">Top up</Badge>
                          )}
                        </span>
                      ))}
                      {set.unlock_count > 0 ? (
                        <Badge tone="green">
                          Unlocks {set.unlock_count} recipe{set.unlock_count === 1 ? '' : 's'}
                        </Badge>
                      ) : (
                        <Badge>
                          Helps with {set.near_unlock_count} recipe{set.near_unlock_count === 1 ? '' : 's'}
                        </Badge>
                      )}
                      {set.synergy_count > 0 && unlockSize > 1 && (
                        <Badge tone="amber">{set.synergy_count} need the full set</Badge>
                      )}
                    </div>
                    {set.unlocked_recipes.length > 0 && (
                      <p className="mt-1 truncate text-xs text-muted">
                        {set.unlocked_recipes.map((recipe, recipeIndex) => (
                          <span key={recipe.id}>
                            {recipeIndex > 0 && ' · '}
                            <Link
                              to="/recipes/$recipeId"
                              params={{ recipeId: recipe.id }}
                              className="hover:text-ink hover:underline"
                            >
                              {recipe.title}
                            </Link>
                          </span>
                        ))}
                      </p>
                    )}
                    {set.unlock_count > 0 && set.near_unlock_count > 0 && (
                      <p className="mt-1 text-xs text-muted">
                        Also gets you closer to {set.near_unlock_count} more.
                      </p>
                    )}
                  </div>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={addUnlockSet.isPending}
                    onClick={() => (
                      unlockSize === 1
                        ? openUnlockSuggestion(set.ingredients[0])
                        : applyUnlockSet(set)
                    )}
                  >
                    {unlockSize === 1
                      ? set.ingredients[0].status === 'insufficient'
                        ? 'Update amount'
                        : 'Add to fridge'
                      : set.ingredients.some((ingredient) => ingredient.status === 'missing')
                        ? 'Add all'
                        : 'Review amounts'}
                  </Button>
                </li>
              ))}
            </ol>
            {unlocks.data.quality_excluded_recipe_count > 0 && (
              <p className="border-t border-line bg-sand/40 px-5 py-3 text-xs text-muted">
                {unlocks.data.quality_excluded_recipe_count} recipe
                {unlocks.data.quality_excluded_recipe_count === 1 ? ' was' : 's were'} excluded
                because an ingredient could not be parsed reliably.
              </p>
            )}
          </div>
        ) : (
          <p className="p-5 text-sm text-muted">
            No additions to recommend yet. Enable a completed cookbook or keep your pantry current.
          </p>
        )}
      </Card>

      {(pantry.data?.items.length || 0) > 0 && (
        <div className="relative mt-6 max-w-md">
          <Search className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <Input
            aria-label="Search your ingredients"
            className="pl-10"
            placeholder="Search your fridge and pantry"
            value={pantryQuery}
            onChange={(event) => setPantryQuery(event.target.value)}
          />
        </div>
      )}

      {pantry.isLoading ? (
        <div className="mt-7 grid gap-5 md:grid-cols-2">
          {[1, 2, 3, 4].map((item) => <Skeleton key={item} className="h-40 rounded-2xl" />)}
        </div>
      ) : pantry.isError ? (
        <Card className="mt-7 p-8 text-center">
          <p className="font-bold text-ink">Your fridge didn’t load.</p>
          <p className="mt-1 text-sm text-muted">{pantry.error.message}</p>
          <Button className="mt-4" onClick={() => void pantry.refetch()}>Try again</Button>
        </Card>
      ) : (pantry.data?.items.length || 0) === 0 ? (
        <Card className="mt-7 grid place-items-center p-12 text-center">
          <span className="grid size-16 place-items-center rounded-full bg-sand text-sage"><Wheat className="size-7" /></span>
          <h2 className="mt-4 font-display text-2xl font-bold text-ink">Your fridge is waiting</h2>
          <p className="mt-2 max-w-sm text-sm text-muted">Add a few ingredients to discover what you can cook.</p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <Button
              variant="secondary"
              disabled={scanPhoto.isPending || scanReceipt.isPending}
              onClick={() => scanInputRef.current?.click()}
            >
              <Camera className="size-4" />
              {scanPhoto.isPending ? 'Scanning…' : 'Scan groceries'}
            </Button>
            <Button
              variant="secondary"
              disabled={scanPhoto.isPending || scanReceipt.isPending}
              onClick={() => receiptInputRef.current?.click()}
            >
              <Receipt className="size-4" />
              {scanReceipt.isPending ? 'Scanning…' : 'Scan receipt'}
            </Button>
            <Button variant="secondary" onClick={() => setTextOpen(true)}>
              <NotebookPen className="size-4" /> Update from notes
            </Button>
            <Button variant="secondary" onClick={() => setQuickOpen(true)}>
              <Sparkles className="size-4" /> Pick common staples
            </Button>
            <Button onClick={() => openAddDialog()}><Plus className="size-4" /> Add your first ingredient</Button>
          </div>
        </Card>
      ) : Object.keys(groups).length === 0 ? (
        <Card className="mt-7 p-8 text-center">
          <p className="font-bold text-ink">No ingredients match “{pantryQuery}”.</p>
          <Button className="mt-4" variant="secondary" onClick={() => setPantryQuery('')}>Clear search</Button>
        </Card>
      ) : (
        <div className="mt-7 grid gap-5 md:grid-cols-2">
          {Object.entries(groups).map(([category, items]) => (
            <Card key={category} className="p-5">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <h2 className="font-display text-xl font-bold text-ink">{category}</h2>
                  <button
                    type="button"
                    aria-label={`Add ingredient to ${category}`}
                    className="grid size-7 shrink-0 place-items-center rounded-full text-muted hover:bg-sand hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sage"
                    onClick={() => openAddDialog(category)}
                  >
                    <Plus className="size-4" />
                  </button>
                </div>
                <Badge>{items.length} items</Badge>
              </div>
              <ul className="flex flex-wrap gap-2">
                {items.map((item) => (
                  <li key={item.id} className="group flex items-center gap-2 rounded-full border border-line bg-cream py-1.5 pl-3 pr-1.5">
                    <span className="text-sm font-semibold text-ink">{itemName(item)}</span>
                    {(item.quantity != null || item.unit) && (
                      <span className="text-xs text-muted">{formatQuantity(item.quantity, item.unit)}</span>
                    )}
                    {(item.expires_at || item.expiry_date) && (
                      <span title={`Expires ${formatDate(item.expires_at || item.expiry_date || '')}`}>
                        <CalendarDays className="size-3 text-terracotta" />
                      </span>
                    )}
                    {expiryState(item.expires_at || item.expiry_date) && (
                      <Badge tone={expiryState(item.expires_at || item.expiry_date)?.tone}>
                        {expiryState(item.expires_at || item.expiry_date)?.label}
                      </Badge>
                    )}
                    <button
                      aria-label={`Edit ${itemName(item)}`}
                      className="grid size-7 place-items-center rounded-full text-muted hover:bg-sand hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sage"
                      onClick={() => startEditing(item)}
                    >
                      <Pencil className="size-3.5" />
                    </button>
                    <button
                      aria-label={`Remove ${itemName(item)}`}
                      className="grid size-7 place-items-center rounded-full text-muted hover:bg-rose-100 hover:text-rose-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sage"
                      onClick={() => removeItem.mutate(item.id)}
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}

      <Dialog
        open={open}
        onClose={() => {
          setOpen(false)
          setPreferredCategory(null)
        }}
        title={preferredCategory ? `Add to ${preferredCategory}` : 'Add an ingredient'}
      >
        <form className="grid gap-4" onSubmit={submit}>
          <Field label="Ingredient">
            <div className="relative">
              <Search className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
              <Input
                autoFocus
                className="pl-10"
                placeholder="Try tomatoes, rice, or basil"
                value={selected?.name || ingredientQuery}
                onChange={(event) => { setSelected(null); setIngredientQuery(event.target.value) }}
              />
            </div>
          </Field>
          {!selected && ingredients.data && ingredients.data.items.length > 0 && (
            <div className="-mt-2 max-h-40 overflow-auto rounded-xl border border-line bg-white p-1 shadow-lg">
              {ingredients.data.items.map((ingredient) => (
                <button
                  type="button"
                  key={ingredient.id}
                  className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm font-semibold text-ink hover:bg-sand"
                  onClick={() => { setSelected(ingredient); setIngredientQuery(ingredient.name) }}
                >
                  {ingredient.name}<span className="text-xs font-normal text-muted">{ingredient.category}</span>
                </button>
              ))}
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Quantity"><Input min="0" step="any" type="number" placeholder="2" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></Field>
            <Field label="Unit">
              <Select value={unit} onChange={(event) => setUnit(event.target.value)}>
                <option value="">None</option>
                {UNIT_GROUPS.map((group) => (
                  <optgroup key={group.label} label={group.label}>
                    {group.units.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </optgroup>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="Best before" hint="Optional"><Input type="date" value={expiry} onChange={(event) => setExpiry(event.target.value)} /></Field>
          {formError && <p role="alert" className="text-sm font-semibold text-rose-700">{formError}</p>}
          <Button className="mt-2 w-full" type="submit" disabled={addItem.isPending || (!selected && !ingredientQuery.trim())}>
            {addItem.isPending ? 'Adding…' : 'Add to fridge'}
          </Button>
        </form>
      </Dialog>

      <Dialog
        open={quickOpen}
        onClose={() => setQuickOpen(false)}
        title="Quick add pantry staples"
        className="sm:max-w-2xl"
      >
        <div className="grid gap-4">
          <p className="text-sm text-muted">
            Check everything you usually keep on hand. Leave quantity blank to use each item’s default amount.
          </p>
          <div className="relative">
            <Search className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <Input
              autoFocus
              aria-label="Search common ingredients"
              className="pl-10"
              placeholder="Search 100 common ingredients"
              value={commonQuery}
              onChange={(event) => setCommonQuery(event.target.value)}
            />
          </div>
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="font-semibold text-muted">{selectedCommon.size} selected</span>
            <div className="flex gap-1">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setSelectedCommon((current) => {
                  const next = new Set(current)
                  filteredCommon.forEach((item) => {
                    if (!pantryNames.has(item.name)) next.add(item.name)
                  })
                  return next
                })}
              >
                Select shown
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setSelectedCommon(new Set())
                  setCommonQuantities({})
                  setCommonUnits({})
                }}
              >
                Clear
              </Button>
            </div>
          </div>
          <div className="max-h-[44vh] overflow-auto rounded-2xl border border-line bg-white p-2">
            {commonIngredients.isLoading ? (
              <div className="grid gap-2 p-1">{[1, 2, 3, 4, 5].map((item) => <Skeleton key={item} className="h-11" />)}</div>
            ) : commonIngredients.isError ? (
              <div className="p-5 text-center text-sm text-muted">
                <p>Common ingredients didn’t load.</p>
                <Button className="mt-3" size="sm" variant="secondary" onClick={() => void commonIngredients.refetch()}>Try again</Button>
              </div>
            ) : filteredCommon.length === 0 ? (
              <p className="p-5 text-center text-sm text-muted">No common ingredients match your search.</p>
            ) : (
              <div className="grid gap-1 sm:grid-cols-2">
                {filteredCommon.map((item) => {
                  const alreadyAdded = pantryNames.has(item.name)
                  const checked = selectedCommon.has(item.name)
                  const defaultLabel = formatQuantity(Number(item.default_quantity), item.default_unit)
                  return (
                    <div
                      key={item.name}
                      className={`rounded-xl p-2.5 ${
                        alreadyAdded ? 'bg-sand/70 opacity-65' : 'hover:bg-sand'
                      }`}
                    >
                      <label className={`flex items-center gap-3 ${alreadyAdded ? 'cursor-default' : 'cursor-pointer'}`}>
                        <input
                          className="sr-only"
                          type="checkbox"
                          checked={checked || alreadyAdded}
                          disabled={alreadyAdded}
                          onChange={() => setSelectedCommon((current) => {
                            const next = new Set(current)
                            if (next.has(item.name)) {
                              next.delete(item.name)
                              setCommonQuantities((quantities) => {
                                const { [item.name]: _, ...rest } = quantities
                                return rest
                              })
                              setCommonUnits((units) => {
                                const { [item.name]: _, ...rest } = units
                                return rest
                              })
                            } else {
                              next.add(item.name)
                            }
                            return next
                          })}
                        />
                        <span className={`grid size-5 shrink-0 place-items-center rounded-md border ${
                          checked || alreadyAdded ? 'border-sage bg-sage text-white' : 'border-line bg-white'
                        }`}>
                          {(checked || alreadyAdded) && <Check className="size-3" />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <b className="block truncate text-sm capitalize text-ink">{item.name}</b>
                          <span className="block truncate text-[11px] text-muted">
                            {alreadyAdded ? 'Already added' : `${item.category} · default ${defaultLabel}`}
                          </span>
                        </span>
                      </label>
                      {checked && !alreadyAdded && (
                        <div className="mt-2 grid grid-cols-[1fr_1.1fr] gap-2 pl-8">
                          <Input
                            aria-label={`Quantity for ${item.name}`}
                            className="h-8"
                            min="0"
                            step="any"
                            type="number"
                            placeholder={String(item.default_quantity)}
                            value={commonQuantities[item.name] || ''}
                            onChange={(event) => setCommonQuantities((current) => ({
                              ...current,
                              [item.name]: event.target.value,
                            }))}
                          />
                          <Select
                            aria-label={`Unit for ${item.name}`}
                            className="h-8"
                            value={commonUnits[item.name] || ''}
                            onChange={(event) => setCommonUnits((current) => ({
                              ...current,
                              [item.name]: event.target.value,
                            }))}
                          >
                            <option value="">Default ({item.default_unit})</option>
                            {UNIT_GROUPS.map((group) => (
                              <optgroup key={group.label} label={group.label}>
                                {group.units.map(([value, label]) => (
                                  <option key={value} value={value}>{label}</option>
                                ))}
                              </optgroup>
                            ))}
                          </Select>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
          <Button
            className="w-full"
            disabled={selectedCommon.size === 0 || addCommon.isPending}
            onClick={submitCommon}
          >
            {addCommon.isPending ? 'Adding…' : `Add ${selectedCommon.size || ''} selected`}
          </Button>
        </div>
      </Dialog>

      <Dialog
        open={textOpen}
        onClose={() => {
          setTextOpen(false)
          setTextError('')
        }}
        title="Update from notes"
      >
        <form className="grid gap-4" onSubmit={submitTextUpdate}>
          <p className="text-sm text-muted">
            Paste a short note about what you bought or used. We’ll parse it and update your fridge.
          </p>
          <Field label="Inventory notes" hint='Try: "Used 2 eggs. Bought 3 tomatoes. Finished the spinach."'>
            <textarea
              autoFocus
              className="min-h-36 w-full rounded-xl border border-line bg-white px-3.5 py-3 text-sm text-ink outline-none placeholder:text-muted/70 focus:border-sage focus:ring-3 focus:ring-sage/15 disabled:bg-sand"
              placeholder={'Used 2 eggs\nBought a loaf of bread\nFinished the milk'}
              value={inventoryText}
              onChange={(event) => setInventoryText(event.target.value)}
            />
          </Field>
          {textError && <p role="alert" className="text-sm font-semibold text-rose-700">{textError}</p>}
          <Button className="w-full" type="submit" disabled={applyTextUpdate.isPending || !inventoryText.trim()}>
            {applyTextUpdate.isPending ? 'Updating…' : 'Apply to fridge'}
          </Button>
        </form>
      </Dialog>

      <Dialog
        open={scanOpen}
        onClose={() => {
          if (confirmScan.isPending) return
          setScanOpen(false)
          setScanError('')
        }}
        title={scanMode === 'receipt' ? 'Review receipt items' : 'Review scanned groceries'}
        className="sm:max-w-2xl"
      >
        <form className="grid gap-4" onSubmit={submitScanConfirm}>
          <p className="text-sm text-muted">
            Edit names and amounts, remove anything wrong, or add a missing item before saving.
          </p>
          <div className="max-h-[50vh] space-y-3 overflow-auto pr-1">
            {scanDrafts.map((row) => {
              const alreadyInFridge = pantryNames.has(row.name.trim().toLowerCase())
              return (
                <div
                  key={row.key}
                  className="rounded-2xl border border-line bg-white p-3"
                >
                  <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1 grid gap-2">
                      <Field label="Ingredient">
                        <Input
                          value={row.name}
                          placeholder="Ingredient name"
                          onChange={(event) =>
                            updateScanDraft(row.key, { name: event.target.value })
                          }
                        />
                      </Field>
                      <div className="grid grid-cols-2 gap-2">
                        <Field label="Quantity">
                          <Input
                            min="0"
                            step="any"
                            type="number"
                            placeholder="2"
                            value={row.quantity}
                            onChange={(event) =>
                              updateScanDraft(row.key, { quantity: event.target.value })
                            }
                          />
                        </Field>
                        <Field label="Unit">
                          <Select
                            value={row.unit}
                            onChange={(event) =>
                              updateScanDraft(row.key, { unit: event.target.value })
                            }
                          >
                            <option value="">None</option>
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
                      {alreadyInFridge && row.name.trim() && (
                        <p className="text-xs font-semibold text-terracotta">
                          {scanMode === 'receipt'
                            ? 'Already in fridge — quantity will be added'
                            : 'Already in fridge — quantity will be updated'}
                        </p>
                      )}
                    </div>
                    <button
                      type="button"
                      aria-label={`Remove ${row.name || 'ingredient'}`}
                      className="mt-7 grid size-9 shrink-0 place-items-center rounded-full text-muted hover:bg-rose-100 hover:text-rose-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sage"
                      onClick={() => removeScanDraft(row.key)}
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
          <Button type="button" variant="secondary" onClick={addScanDraft}>
            <Plus className="size-4" /> Add ingredient
          </Button>
          {scanError && <p role="alert" className="text-sm font-semibold text-rose-700">{scanError}</p>}
          <Button
            className="w-full"
            type="submit"
            disabled={confirmScan.isPending || scanDrafts.length === 0}
          >
            {confirmScan.isPending ? 'Saving…' : 'Add to fridge'}
          </Button>
        </form>
      </Dialog>

      <Dialog open={Boolean(editing)} onClose={() => setEditing(null)} title={`Edit ${editing ? itemName(editing) : 'ingredient'}`}>
        <form className="grid gap-4" onSubmit={submitEdit}>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Quantity">
              <Input min="0" step="any" type="number" placeholder="2" value={editQuantity} onChange={(event) => setEditQuantity(event.target.value)} />
            </Field>
            <Field label="Unit">
              <Select value={editUnit} onChange={(event) => setEditUnit(event.target.value)}>
                <option value="">None</option>
                {UNIT_GROUPS.map((group) => (
                  <optgroup key={group.label} label={group.label}>
                    {group.units.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </optgroup>
                ))}
              </Select>
            </Field>
          </div>
          <Field label="Best before" hint="Optional">
            <Input type="date" value={editExpiry} onChange={(event) => setEditExpiry(event.target.value)} />
          </Field>
          {editError && <p role="alert" className="text-sm font-semibold text-rose-700">{editError}</p>}
          <Button className="w-full" type="submit" disabled={updateItem.isPending}>
            {updateItem.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </form>
      </Dialog>
    </div>
  )
}
