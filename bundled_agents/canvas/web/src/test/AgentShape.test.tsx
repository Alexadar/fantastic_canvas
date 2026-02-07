import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { AgentShape } from '../components/AgentShape'
import type { CanvasAgent, WSMessage } from '../types'

// Mock the base module (HtmlAgentBody)
vi.mock('../components/base', () => ({
  HtmlAgentBody: ({ html }: any) => (
    <div data-testid="html-body">{html || 'Empty'}</div>
  ),
}))

// Mock plugin registry — terminal + html plugins
vi.mock('../plugins/registry', () => {
  const terminalPlugin = {
    name: 'terminal',
    accentColor: '#666',
    matchAgent: (agent: any) => agent.bundle === 'terminal',
    injectAgent: vi.fn(() => vi.fn()),
    onRefresh: vi.fn(),
  }
  const htmlPlugin = {
    name: 'HTML',
    accentColor: '#f59e0b',
    chromeless: true,
    matchAgent: (agent: any) =>
      agent.bundle === 'html' || !!(agent.html_content || agent.output_html),
    onRefresh: vi.fn(),
  }
  const plugins = [terminalPlugin, htmlPlugin]
  return {
    registry: {
      findPlugin: (agent: any) => plugins.find(p => p.matchAgent(agent)) || null,
      injectAll: vi.fn(() => vi.fn()),
    },
  }
})

function makeAgent(overrides: Partial<CanvasAgent> = {}): CanvasAgent {
  return {
    id: 'test1234',
    display_name: '',
    x: 0,
    y: 0,
    width: 400,
    height: 300,
    output_html: '',
    ...overrides,
  }
}

const defaultProps = {
  send: vi.fn(),
  subscribe: vi.fn(() => () => {}),
  onDragStart: vi.fn(),
}

describe('AgentShape', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  // ─── Header rendering ──────────────────────────────────────────────

  it('renders header with plugin name for bundle agent', () => {
    render(<AgentShape agent={makeAgent({ bundle: 'terminal' })} {...defaultProps} />)
    expect(screen.getByText('terminal')).toBeInTheDocument()
  })

  it('uses display_name when set', () => {
    render(
      <AgentShape
        agent={makeAgent({ display_name: 'My Agent' })}
        {...defaultProps}
      />
    )
    expect(screen.getByText('My Agent')).toBeInTheDocument()
  })

  it('renders HTML label for agents with html_content', () => {
    render(
      <AgentShape
        agent={makeAgent({ html_content: '<h1>Hi</h1>' })}
        {...defaultProps}
      />
    )
    expect(screen.getByText('HTML')).toBeInTheDocument()
  })

  it('renders Agent label for agents without plugin', () => {
    render(
      <AgentShape
        agent={makeAgent({})}
        {...defaultProps}
      />
    )
    expect(screen.getByText('Agent')).toBeInTheDocument()
  })

  // ─── Close button ──────────────────────────────────────────────────

  it('shows close button for all agents', () => {
    render(<AgentShape agent={makeAgent({ bundle: 'terminal' })} {...defaultProps} />)
    const closeBtn = screen.getByTitle('Close agent')
    expect(closeBtn).toBeInTheDocument()
  })

  it('clicking close sends delete_agent', () => {
    const send = vi.fn()
    render(<AgentShape agent={makeAgent({ bundle: 'terminal' })} {...defaultProps} send={send} />)
    fireEvent.click(screen.getByTitle('Close agent'))
    expect(send).toHaveBeenCalledWith({
      type: 'delete_agent',
      agent_id: 'test1234',
    })
  })

  // ─── Body rendering ───────────────────────────────────────────────

  it('renders bundle body div for bundle agent', () => {
    const { container } = render(
      <AgentShape agent={makeAgent({ bundle: 'terminal' })} {...defaultProps} />
    )
    expect(container.querySelector('.agent-bundle-body')).toBeInTheDocument()
  })

  it('renders html body for agent with html_content', () => {
    render(
      <AgentShape
        agent={makeAgent({ html_content: '<h1>Test</h1>' })}
        {...defaultProps}
      />
    )
    expect(screen.getByTestId('html-body')).toBeInTheDocument()
  })

  it('does not render bundle body for non-bundle agent', () => {
    const { container } = render(
      <AgentShape
        agent={makeAgent({ html_content: '<h1>Test</h1>' })}
        {...defaultProps}
      />
    )
    expect(container.querySelector('.agent-bundle-body')).not.toBeInTheDocument()
  })

  // ─── Chromeless mode ───────────────────────────────────────────────

  it('html content agent has chromeless class', () => {
    const { container } = render(
      <AgentShape agent={makeAgent({ html_content: '<h1>Hi</h1>' })} {...defaultProps} />
    )
    const shape = container.querySelector('.agent-shape')
    expect(shape).toHaveClass('agent-chromeless')
  })

  it('bundle agent is not chromeless', () => {
    const { container } = render(
      <AgentShape agent={makeAgent({ bundle: 'terminal' })} {...defaultProps} />
    )
    const shape = container.querySelector('.agent-shape')
    expect(shape).not.toHaveClass('agent-chromeless')
  })

  // ─── Drag start ────────────────────────────────────────────────────

  it('header mousedown triggers onDragStart', () => {
    const onDragStart = vi.fn()
    const { container } = render(
      <AgentShape
        agent={makeAgent({ x: 10, y: 20, bundle: 'terminal' })}
        {...defaultProps}
        onDragStart={onDragStart}
      />
    )
    const header = container.querySelector('.agent-header')!
    fireEvent.mouseDown(header, { button: 0 })
    expect(onDragStart).toHaveBeenCalledWith(
      'test1234', 10, 20, expect.any(Object)
    )
  })

  it('header mousedown with alt key does not trigger drag', () => {
    const onDragStart = vi.fn()
    const { container } = render(
      <AgentShape agent={makeAgent({ bundle: 'terminal' })} {...defaultProps} onDragStart={onDragStart} />
    )
    const header = container.querySelector('.agent-header')!
    fireEvent.mouseDown(header, { button: 0, altKey: true })
    expect(onDragStart).not.toHaveBeenCalled()
  })

  it('right click on header does not trigger drag', () => {
    const onDragStart = vi.fn()
    const { container } = render(
      <AgentShape agent={makeAgent({ bundle: 'terminal' })} {...defaultProps} onDragStart={onDragStart} />
    )
    const header = container.querySelector('.agent-header')!
    fireEvent.mouseDown(header, { button: 2 })
    expect(onDragStart).not.toHaveBeenCalled()
  })

  // ─── Readonly mode (broadcast viewer) ───────────────────────────────

  it('hides close and refresh buttons when readonly', () => {
    render(
      <AgentShape agent={makeAgent({ bundle: 'terminal' })} {...defaultProps} readonly={true} />
    )
    expect(screen.queryByTitle('Close agent')).not.toBeInTheDocument()
    expect(screen.queryByTitle('Refresh agent')).not.toBeInTheDocument()
  })

  it('shows close and refresh buttons when not readonly', () => {
    render(
      <AgentShape agent={makeAgent({ bundle: 'terminal' })} {...defaultProps} readonly={false} />
    )
    expect(screen.getByTitle('Close agent')).toBeInTheDocument()
    expect(screen.getByTitle('Refresh agent')).toBeInTheDocument()
  })
})
