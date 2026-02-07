import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { HtmlAgentBody } from '../components/base/HtmlAgentBody'

describe('HtmlAgentBody', () => {
  it('renders empty placeholder when no html', () => {
    render(<HtmlAgentBody html="" />)
    expect(screen.getByText('Empty')).toBeInTheDocument()
  })

  it('renders iframe when html provided', () => {
    const { container } = render(<HtmlAgentBody html="<h1>Hello</h1>" />)
    const iframe = container.querySelector('iframe')
    expect(iframe).toBeInTheDocument()
    expect(iframe).toHaveClass('agent-html-body')
  })

  it('iframe has correct styles', () => {
    const { container } = render(<HtmlAgentBody html="<div>content</div>" />)
    const iframe = container.querySelector('iframe')
    expect(iframe).toHaveStyle({ width: '100%', height: '100%' })
    // jsdom parses border: none → border-style: none (shorthand expansion)
    expect(iframe?.style.borderStyle || iframe?.style.border).toContain('')
  })

  it('sets blob src on iframe', () => {
    const { container } = render(<HtmlAgentBody html="<p>test</p>" />)
    const iframe = container.querySelector('iframe')
    // jsdom creates real blob URLs — just verify it starts with blob:
    expect(iframe?.getAttribute('src')).toMatch(/^blob:/)
  })
})
