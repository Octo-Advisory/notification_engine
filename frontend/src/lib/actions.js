import { useCallback, useContext } from 'react'
import { FrappeContext } from 'frappe-react-sdk'
import { useToast } from '../components/Toast.jsx'
import { errorText } from './format.js'

const WAITING = ['Queued', 'Throttled']
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// Direct access to frappe-js-sdk's call object, for one-off actions that are not data hooks.
export function useCall() {
  return useContext(FrappeContext).call
}

// Wait (up to ~25 s) until queued test messages are delivered, then toast the outcome.
export function useWaitForLogs() {
  const call = useCall()
  const toast = useToast()
  return useCallback(
    async (names) => {
      names = (names || []).filter(Boolean)
      if (!names.length) {
        toast('Nothing was queued (a message with the same content may already exist).', 'info')
        return
      }
      toast(`Test message queued. Waiting for delivery…`, 'info')
      let rows = []
      for (let i = 0; i < 25; i++) {
        await sleep(1000)
        const r = await call.get('notification_engine.teams.api.get_log_status', { names: JSON.stringify(names) })
        rows = r.message || []
        if (rows.length && rows.every((x) => !WAITING.includes(x.status))) break
      }
      for (const row of rows) {
        if (row.status === 'Sent') toast(`Delivered to ${row.destination}.`, 'good')
        else if (WAITING.includes(row.status))
          toast(`${row.destination}: still ${row.status.toLowerCase()}. Are background workers running?`, 'info')
        else toast(`${row.destination}: ${row.status}. ${row.error || ''}`, 'bad')
      }
      return rows
    },
    [call, toast]
  )
}

export function useSendTestToDestination() {
  const call = useCall()
  const toast = useToast()
  const wait = useWaitForLogs()
  return useCallback(
    async (destination) => {
      try {
        const r = await call.post('notification_engine.teams.api.send_test_to_destination', { destination })
        return await wait([r.message])
      } catch (e) {
        toast(errorText(e), 'bad')
      }
    },
    [call, toast, wait]
  )
}

export function useSendTestForRule() {
  const call = useCall()
  const toast = useToast()
  const wait = useWaitForLogs()
  return useCallback(
    async (rule) => {
      try {
        const r = await call.post('notification_engine.teams.api.send_test_for_rule', { rule })
        const res = r.message || {}
        if (res.condition_error) toast(`Condition error: ${res.condition_error}`, 'bad')
        else if (res.condition === false)
          toast(`Note: the condition is false for ${res.docname}, so a real event would not send.`, 'info')
        return await wait(res.logs)
      } catch (e) {
        toast(errorText(e), 'bad')
      }
    },
    [call, toast, wait]
  )
}

export function useResend() {
  const call = useCall()
  const toast = useToast()
  return useCallback(
    async (names) => {
      try {
        const r = await call.post('notification_engine.teams.api.resend', { names: JSON.stringify(names) })
        toast(`${r.message} message(s) queued again.`, 'good')
        return r.message
      } catch (e) {
        toast(errorText(e), 'bad')
      }
    },
    [call, toast]
  )
}
