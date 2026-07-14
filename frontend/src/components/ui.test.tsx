import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Button, Dialog } from './ui'

describe('Button', () => {
  it('is accessible and invokes its action', async () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Add ingredient</Button>)
    const button = screen.getByRole('button', { name: 'Add ingredient' })
    button.click()
    expect(onClick).toHaveBeenCalledOnce()
  })
})

describe('Dialog', () => {
  it('closes when Escape is pressed', () => {
    const onClose = vi.fn()
    render(
      <Dialog open onClose={onClose} title="Add ingredient">
        Content
      </Dialog>,
    )

    fireEvent.keyDown(window, { key: 'Escape' })

    expect(onClose).toHaveBeenCalledOnce()
  })
})
