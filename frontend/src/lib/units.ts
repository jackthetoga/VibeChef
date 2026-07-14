export const UNIT_GROUPS = [
  {
    label: 'Count',
    units: [
      ['pieces', 'pieces'],
      ['whole', 'whole'],
      ['cloves', 'cloves'],
      ['cans', 'cans'],
      ['bunches', 'bunches'],
      ['packages', 'packages'],
    ],
  },
  {
    label: 'Weight',
    units: [
      ['mg', 'mg'],
      ['g', 'g'],
      ['kg', 'kg'],
      ['oz', 'oz'],
      ['lb', 'lb'],
    ],
  },
  {
    label: 'Volume',
    units: [
      ['ml', 'ml'],
      ['l', 'L'],
      ['tsp', 'tsp'],
      ['tbsp', 'tbsp'],
      ['fl oz', 'fl oz'],
      ['cups', 'cups'],
      ['pt', 'pints'],
      ['qt', 'quarts'],
      ['gal', 'gallons'],
    ],
  },
] as const

export function formatQuantity(quantity?: number | null, unit?: string | null) {
  if (quantity == null && !unit) return ''
  const formattedQuantity =
    quantity == null ? '' : new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(quantity)
  return [formattedQuantity, unit].filter(Boolean).join(' ')
}
