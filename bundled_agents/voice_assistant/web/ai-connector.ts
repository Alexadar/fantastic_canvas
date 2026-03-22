/**
 * AI Connector — bridges voice UI to the fantastic WS backend.
 *
 * Sends transcripts, receives streamed AI responses.
 * The actual AI logic lives server-side in tools.py;
 * this is just the WS message adapter.
 */

export interface AiConnectorEvents {
  /** Streamed response chunk from AI */
  onResponseChunk: (text: string, done: boolean) => void
  /** AI state changed */
  onStateChange: (state: 'idle' | 'thinking' | 'responding') => void
  /** Error from backend */
  onError: (error: string) => void
}

export interface AiConnector {
  /** Send committed transcript to AI backend */
  sendTranscript(text: string): void
  /** Signal that user interrupted (barge-in) */
  sendInterrupt(): void
  /** Process incoming WS message (called by plugin) */
  handleMessage(msg: any): void
}

export function createAiConnector(
  agentId: string,
  wsSend: (msg: any) => void,
  events: AiConnectorEvents,
): AiConnector {
  let responseBuffer = ''

  return {
    sendTranscript(text: string) {
      wsSend({
        type: 'voice_transcript',
        agent_id: agentId,
        text,
        is_final: true,
      })
      events.onStateChange('thinking')
    },

    sendInterrupt() {
      wsSend({
        type: 'voice_interrupt',
        agent_id: agentId,
      })
      responseBuffer = ''
      events.onStateChange('idle')
    },

    handleMessage(msg: any) {
      if (msg.agent_id !== agentId) return

      switch (msg.type) {
        case 'voice_response': {
          const chunk = msg.text || ''
          const done = !!msg.done
          responseBuffer += chunk
          if (done) {
            events.onResponseChunk(responseBuffer, true)
            responseBuffer = ''
          } else {
            events.onStateChange('responding')
            events.onResponseChunk(chunk, false)
          }
          break
        }
        case 'voice_state': {
          events.onStateChange(msg.state)
          break
        }
        case 'voice_error': {
          events.onError(msg.error || 'Unknown AI error')
          break
        }
      }
    },
  }
}
