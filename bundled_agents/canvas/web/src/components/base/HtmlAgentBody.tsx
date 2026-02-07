import { useEffect, useState } from 'react'

interface HtmlAgentBodyProps {
  html: string
}

export function HtmlAgentBody({ html }: HtmlAgentBodyProps) {
  const [url, setUrl] = useState('')

  useEffect(() => {
    if (!html) return
    const doc = `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:transparent}</style>
</head><body>${html}</body></html>`
    const blob = new Blob([doc], { type: 'text/html' })
    const u = URL.createObjectURL(blob)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [html])

  if (!html) {
    return <div className="agent-body-placeholder">Empty</div>
  }

  return (
    <iframe
      src={url}
      className="agent-html-body"
      allowTransparency
      style={{ width: '100%', height: '100%', border: 'none', background: 'transparent' }}
    />
  )
}
