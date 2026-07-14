import { useEffect, useRef, useState } from 'react'
import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  FileUp,
  LoaderCircle,
  RefreshCw,
  Trash2,
  UploadCloud,
} from 'lucide-react'
import { toast } from 'sonner'
import { cookbooksApi } from '../lib/api/client'
import type { Cookbook } from '../lib/api/types'
import { Badge, Button, Card, Dialog, Skeleton } from '../components/ui'

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

function title(book: Cookbook) {
  return book.title || book.name || book.original_filename || book.filename || 'Untitled cookbook'
}

function CookbookCover({ book }: { book: Cookbook }) {
  const [src, setSrc] = useState<string | null>(null)

  useEffect(() => {
    if (!book.cover_url) {
      setSrc(null)
      return
    }
    let objectUrl: string | null = null
    let cancelled = false
    void cookbooksApi
      .coverBlob(book.id)
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
  }, [book.id, book.cover_url])

  if (src) {
    return (
      <img
        src={src}
        alt=""
        className="h-28 w-20 shrink-0 rounded-xl object-cover shadow-md"
      />
    )
  }

  return (
    <div className="grid h-28 w-20 shrink-0 place-items-center overflow-hidden rounded-xl bg-gradient-to-br from-terracotta to-amber-300 text-white shadow-md">
      <BookOpen className="size-8" />
    </div>
  )
}

export function LibraryPage() {
  const client = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const previousStatuses = useRef(new Map<string, string>())
  const [dragging, setDragging] = useState(false)
  const [pendingRemove, setPendingRemove] = useState<Cookbook | null>(null)
  const books = useQuery({
    queryKey: ['cookbooks'],
    queryFn: cookbooksApi.list,
    refetchInterval: (query) =>
      query.state.data?.items.some((book) => ['pending', 'processing'].includes(book.status))
        ? 3000
        : false,
  })
  const pendingUploads = useIsMutating({ mutationKey: ['cookbook-upload'] })
  const upload = useMutation({
    mutationKey: ['cookbook-upload'],
    mutationFn: cookbooksApi.upload,
    onSuccess: () => {
      toast.success('Cookbook uploaded. We’re finding recipes now.')
      void client.invalidateQueries({ queryKey: ['cookbooks'] })
    },
    onError: (error) => toast.error(error.message),
  })

  useEffect(() => {
    const current = new Map<string, string>()
    let importCompleted = false
    for (const book of books.data?.items || []) {
      const previous = previousStatuses.current.get(book.id)
      if (book.status === 'completed' && previous !== 'completed') {
        importCompleted = true
      }
      current.set(book.id, book.status)
    }
    previousStatuses.current = current
    if (importCompleted) void client.invalidateQueries({ queryKey: ['recipes'] })
  }, [books.data, client])

  const remove = useMutation({
    mutationFn: cookbooksApi.remove,
    onSuccess: () => {
      toast.success('Cookbook removed from your library')
      setPendingRemove(null)
      void client.invalidateQueries({ queryKey: ['cookbooks'] })
      void client.invalidateQueries({ queryKey: ['recipes'] })
    },
    onError: (error) => toast.error(error.message),
  })
  const retry = useMutation({
    mutationFn: cookbooksApi.retry,
    onSuccess: () => {
      toast.success('Re-import started')
      void client.invalidateQueries({ queryKey: ['cookbooks'] })
    },
    onError: (error) => toast.error(error.message),
  })

  const uploadFiles = (files: FileList | File[]) => {
    Array.from(files).forEach((file) => {
      if (!/\.(pdf|epub|txt)$/i.test(file.name)) {
        toast.error(`${file.name} isn’t a supported cookbook format. Use PDF, EPUB, or TXT.`)
        return
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        toast.error(`${file.name} exceeds the 50 MB upload limit.`)
        return
      }
      upload.mutate(file)
    })
  }

  return (
    <div className="mx-auto max-w-6xl p-4 sm:p-8 xl:p-10">
      <div>
        <p className="mb-2 text-xs font-bold uppercase tracking-[.18em] text-terracotta">Your collection</p>
        <h1 className="font-display text-4xl font-bold text-ink sm:text-5xl">Cookbook library</h1>
        <p className="mt-2 text-muted">Upload a cookbook and turn every page into searchable recipes.</p>
      </div>

      <button
        className={`mt-8 grid w-full place-items-center rounded-3xl border-2 border-dashed p-9 text-center transition focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-sage/30 ${
          dragging ? 'border-sage bg-leaf/10' : 'border-line bg-white hover:border-sage hover:bg-sand/60'
        }`}
        onClick={() => inputRef.current?.click()}
        onDragEnter={(event) => { event.preventDefault(); setDragging(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); uploadFiles(event.dataTransfer.files) }}
      >
        <span className="grid size-16 place-items-center rounded-2xl bg-sage text-white shadow-sm">
          {pendingUploads > 0 ? <LoaderCircle className="size-7 animate-spin" /> : <UploadCloud className="size-7" />}
        </span>
        <span className="mt-4 font-display text-xl font-bold text-ink">Drop your cookbook here</span>
        <span className="mt-1 text-sm text-muted">or click to browse · PDF, EPUB, or TXT</span>
        <span className="mt-4 rounded-full bg-sand px-3 py-1 text-xs font-semibold text-muted">Up to 50 MB</span>
        <input
          ref={inputRef}
          className="sr-only"
          type="file"
          multiple
          accept=".pdf,.epub,.txt,application/pdf,application/epub+zip,text/plain"
          onChange={(event) => {
            if (event.target.files) uploadFiles(event.target.files)
            event.target.value = ''
          }}
        />
      </button>

      <div className="mb-4 mt-9 flex items-center justify-between">
        <h2 className="font-display text-2xl font-bold text-ink">Your cookbooks</h2>
        <Badge>{books.data?.items.length || 0} books</Badge>
      </div>

      {books.isLoading ? (
        <div className="grid gap-5 md:grid-cols-2">
          {[1, 2, 3, 4].map((item) => <Skeleton key={item} className="h-44 rounded-2xl" />)}
        </div>
      ) : books.isError ? (
        <Card className="p-8 text-center">
          <p className="font-bold text-ink">We couldn’t open your library.</p>
          <p className="mt-1 text-sm text-muted">{books.error.message}</p>
          <Button className="mt-4" onClick={() => void books.refetch()}>Try again</Button>
        </Card>
      ) : books.data?.items.length === 0 ? (
        <Card className="grid place-items-center p-10 text-center">
          <BookOpen className="size-10 text-sage" />
          <h3 className="mt-3 font-display text-xl font-bold text-ink">The shelf is empty</h3>
          <p className="mt-1 text-sm text-muted">Upload your first cookbook to get started.</p>
          <Button className="mt-4" onClick={() => inputRef.current?.click()}>
            <UploadCloud className="size-4" /> Upload a cookbook
          </Button>
        </Card>
      ) : (
        <div className="grid gap-5 md:grid-cols-2">
          {books.data?.items.map((book) => {
            const processing = ['pending', 'processing'].includes(book.status)
            const failed = book.status === 'failed'
            const progress = book.progress == null ? undefined : book.progress <= 1 ? book.progress * 100 : book.progress
            return (
              <Card key={book.id} className="flex gap-4 p-5">
                <CookbookCover book={book} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h3 className="truncate font-display text-lg font-bold text-ink">{title(book)}</h3>
                      <p className="mt-1 text-xs font-semibold text-muted">{book.recipe_count || 0} recipes</p>
                    </div>
                    <Button
                      aria-label={`Remove ${title(book)}`}
                      variant="ghost"
                      size="icon"
                      className="shrink-0 text-muted hover:bg-rose-100 hover:text-rose-700"
                      onClick={() => setPendingRemove(book)}
                      disabled={remove.isPending}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                  <div className="mt-4">
                    {processing ? (
                      <>
                        <p className="flex items-center gap-1.5 text-xs font-bold text-amber-800"><LoaderCircle className="size-3.5 animate-spin" /> Processing recipes…</p>
                        <div className="mt-2 h-2 overflow-hidden rounded-full bg-sand">
                          <div className="h-full rounded-full bg-terracotta transition-all" style={{ width: `${progress ?? 45}%` }} />
                        </div>
                      </>
                    ) : failed ? (
                      <div className="grid gap-3">
                        <p className="flex items-start gap-1.5 text-xs font-semibold text-rose-700">
                          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {book.error || 'Import failed. Try again or remove this book.'}
                        </p>
                        <div className="flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={retry.isPending}
                            onClick={() => retry.mutate(book.id)}
                          >
                            <RefreshCw className={`size-3.5 ${retry.isPending ? 'animate-spin' : ''}`} />
                            Retry import
                          </Button>
                          <Button size="sm" variant="danger" onClick={() => setPendingRemove(book)}>
                            <Trash2 className="size-3.5" /> Remove
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-center justify-between gap-2">
                        <p className="flex items-center gap-1.5 text-xs font-bold text-leaf-dark"><CheckCircle2 className="size-4" /> Ready to cook</p>
                        <button
                          className="text-xs font-bold text-muted hover:text-rose-700"
                          onClick={() => setPendingRemove(book)}
                        >
                          Remove
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            )
          })}
          {pendingUploads > 0 && (
            <Card className="flex items-center gap-4 border-dashed p-5">
              <span className="grid size-14 place-items-center rounded-xl bg-sand text-sage"><FileUp className="size-6" /></span>
              <div><b className="text-ink">Uploading {pendingUploads} cookbook{pendingUploads === 1 ? '' : 's'}…</b><p className="text-sm text-muted">Keep this window open.</p></div>
            </Card>
          )}
        </div>
      )}

      <Dialog
        open={Boolean(pendingRemove)}
        onClose={() => !remove.isPending && setPendingRemove(null)}
        title="Remove cookbook?"
      >
        <p className="text-sm leading-relaxed text-muted">
          <b className="text-ink">{pendingRemove ? title(pendingRemove) : 'This cookbook'}</b>
          {' '}will be removed from your library, along with any recipes extracted from it.
          Your fridge ingredients are kept.
        </p>
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <Button variant="secondary" disabled={remove.isPending} onClick={() => setPendingRemove(null)}>
            Keep cookbook
          </Button>
          <Button
            variant="danger"
            disabled={!pendingRemove || remove.isPending}
            onClick={() => pendingRemove && remove.mutate(pendingRemove.id)}
          >
            {remove.isPending ? 'Removing…' : 'Remove cookbook'}
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
