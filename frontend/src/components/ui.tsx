import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  InputHTMLAttributes,
  SelectHTMLAttributes,
} from 'react'
import { useEffect } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { X } from 'lucide-react'
import { cn } from '../lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-sage/30 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        primary: 'bg-ink text-cream shadow-sm hover:bg-sage-dark',
        secondary: 'border border-line bg-white text-ink hover:bg-sand',
        ghost: 'text-ink hover:bg-sand',
        danger: 'bg-rose-100 text-rose-800 hover:bg-rose-200',
      },
      size: {
        sm: 'h-9 px-3',
        md: 'h-11 px-4',
        lg: 'h-13 px-6 text-base',
        icon: 'size-10',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export function Button({ className, variant, size, type = 'button', ...props }: ButtonProps) {
  return <button type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'h-11 w-full rounded-xl border border-line bg-white px-3.5 text-sm text-ink outline-none placeholder:text-muted/70 focus:border-sage focus:ring-3 focus:ring-sage/15 disabled:bg-sand',
        className,
      )}
      {...props}
    />
  )
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'h-11 max-w-full rounded-xl border border-line bg-white px-3.5 text-sm font-medium text-ink outline-none focus:border-sage focus:ring-3 focus:ring-sage/15',
        className,
      )}
      {...props}
    >
      {children}
    </select>
  )
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-2xl border border-line bg-white shadow-card', className)} {...props} />
}

const badgeVariants = cva('inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold', {
  variants: {
    tone: {
      green: 'bg-leaf/12 text-leaf-dark',
      amber: 'bg-amber-100 text-amber-800',
      neutral: 'bg-sand text-muted',
      rose: 'bg-rose-100 text-rose-800',
    },
  },
  defaultVariants: { tone: 'neutral' },
})

export function Badge({
  className,
  tone,
  ...props
}: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />
}

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('animate-pulse rounded-xl bg-stone-200', className)} {...props} />
}

export function Dialog({
  open,
  onClose,
  title,
  children,
  className,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
  className?: string
}) {
  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose, open])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-ink/35 p-0 backdrop-blur-sm sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dialog-title"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div
        className={cn(
          'max-h-[88vh] w-full overflow-auto rounded-t-3xl bg-cream p-5 shadow-2xl sm:max-w-lg sm:rounded-3xl sm:p-6',
          className,
        )}
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 id="dialog-title" className="font-display text-2xl font-bold text-ink">
            {title}
          </h2>
          <Button aria-label="Close dialog" variant="ghost" size="icon" onClick={onClose}>
            <X className="size-5" />
          </Button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="grid gap-1.5 text-sm font-semibold text-ink">
      <span>{label}</span>
      {children}
      {hint && <span className="text-xs font-normal text-muted">{hint}</span>}
    </label>
  )
}
