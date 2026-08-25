// Standalone stub for pytho-app's IntelAgentWs context. The iframe
// version doesn't hold its own WebSocket — parent frame (pytho-app) does,
// and postMessages relevant events in. For useProductChains this is
// sufficient because the hook falls back to polling REST when no WS
// events arrive.

import { useEffect, useRef } from 'react'

export function useIntelAgentWs() {
  const ref = useRef({
    subscribe: (_event: string, _handler: (...args: any[]) => void) => () => {},
    send: (_msg: unknown) => {},
    isOpen: false,
  })
  useEffect(() => {}, [])
  return ref.current
}
