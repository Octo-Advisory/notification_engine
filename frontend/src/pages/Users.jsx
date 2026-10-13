import { useFrappeGetDocList } from 'frappe-react-sdk'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Users as UsersIcon } from 'lucide-react'
import { Card, Empty, ErrorBox, Loading, PageHeader, Pill } from '../components/ui.jsx'
import { dateTime, deskUrl, errorText, timeAgo } from '../lib/format.js'

export default function Users() {
  const { data, error, isLoading } = useFrappeGetDocList('Teams User Map', {
    fields: ['name', 'user', 'teams_name', 'teams_email', 'installed', 'last_seen'],
    orderBy: { field: 'last_seen', order: 'desc' },
    limit: 1000,
  })
  const unlinked = (data || []).filter((u) => !u.user).length

  return (
    <>
      <PageHeader
        title="Teams Users"
        subtitle="People who installed the bot, and the Frappe user each one acts as."
      />
      <ErrorBox error={error && errorText(error)} />
      {unlinked > 0 && (
        <div className="card bg-warn-soft text-warn-text p-3 mb-4 text-[13px] flex gap-2 items-start">
          <AlertTriangle size={16} className="mt-0.5 flex-none" />
          <span>{unlinked} Teams user(s) are not linked to a Frappe user, so they get no personal messages and cannot use card buttons. Their Teams email did not match a Frappe user: open the row and set <b>Frappe User</b>.</span>
        </div>
      )}
      <Card bodyClass="p-0">
        {isLoading ? <Loading /> : !data?.length ? (
          <Empty icon={UsersIcon} title="Nobody has installed the bot yet">
            Rows appear when someone opens the bot in Teams (personal scope). Needs the Teams bot: <Link className="text-accent-text" to="/install#bot">install guide, bot steps</Link>.
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>Teams user</th><th>Frappe user</th><th>App</th><th>Last seen</th></tr></thead>
              <tbody>
                {data.map((u) => (
                  <tr key={u.name}>
                    <td>
                      <a className="font-medium text-ink hover:text-accent-text" href={deskUrl('Teams User Map', u.name)}>{u.teams_name || '(unknown name)'}</a>
                      <div className="text-[12px] text-ink-3">{u.teams_email || 'email not fetched yet'}</div>
                    </td>
                    <td>{u.user ? <span className="inline-flex items-center gap-1.5"><CheckCircle2 size={14} className="text-good-text" /> {u.user}</span>
                      : <Pill tone="warn"><AlertTriangle size={12} /> Not linked</Pill>}</td>
                    <td>{u.installed ? <Pill tone="good">Installed</Pill> : <Pill>Removed</Pill>}</td>
                    <td className="text-ink-2 whitespace-nowrap" title={dateTime(u.last_seen)}>{timeAgo(u.last_seen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}
