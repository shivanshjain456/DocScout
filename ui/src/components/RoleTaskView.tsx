import React, { useState } from 'react'

export interface RoleTaskData {
  task_id: string
  title: string
  stage: number
  term_reference: string
  estimated_hours: number
  role: string
  completed: boolean
  mandatory?: boolean
}

export interface RoleTaskListData {
  role: string
  pending_tasks: RoleTaskData[]
  completed_tasks: RoleTaskData[]
  total_estimated_hours: number
}

export interface RoleTaskViewProps {
  runId?: string
  tenantId?: string
  apiBaseUrl?: string
  apiKey?: string
  className?: string
  initialRole?: string
  initialData?: RoleTaskListData
  onTaskSelected?: (task: RoleTaskData) => void
}

const CANONICAL_ROLES = [
  { id: 'all', label: 'All Roles' },
  { id: 'developer', label: 'Developer' },
  { id: 'qa-engineer', label: 'QA Engineer' },
  { id: 'sre', label: 'SRE' },
  { id: 'engineering-manager', label: 'Engineering Manager' },
  { id: 'compliance-officer', label: 'Compliance Officer' },
]

const DEFAULT_MOCK_DATA: RoleTaskListData = {
  role: 'all',
  pending_tasks: [
    {
      task_id: 'M1-1',
      title: 'Map database dependencies and domain boundary edges',
      stage: 1,
      term_reference: 'TAX-M1-1',
      estimated_hours: 8,
      role: 'sre',
      completed: false,
      mandatory: true,
    },
    {
      task_id: 'M1-2',
      title: 'Draft architectural decoupling ADR and API contracts',
      stage: 1,
      term_reference: 'TAX-M1-2',
      estimated_hours: 8,
      role: 'developer',
      completed: false,
      mandatory: true,
    },
    {
      task_id: 'M3-1',
      title: 'Configure automated boundary regression gates in CI pipeline',
      stage: 3,
      term_reference: 'TAX-M3-1',
      estimated_hours: 12,
      role: 'qa-engineer',
      completed: false,
      mandatory: true,
    },
    {
      task_id: 'M4-2',
      title: 'Conduct final architecture audit review with compliance lead',
      stage: 4,
      term_reference: 'TAX-M4-2',
      estimated_hours: 6,
      role: 'compliance-officer',
      completed: false,
      mandatory: true,
    },
  ],
  completed_tasks: [],
  total_estimated_hours: 34,
}

export const RoleTaskView: React.FC<RoleTaskViewProps> = ({
  runId = 'run-demo-001',
  tenantId = 'default',
  apiBaseUrl = '',
  apiKey = '',
  className = '',
  initialRole = 'all',
  initialData = DEFAULT_MOCK_DATA,
  onTaskSelected,
}) => {
  const [selectedRole, setSelectedRole] = useState<string>(initialRole)
  const [taskData, setTaskData] = useState<RoleTaskListData>(initialData)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const handleRoleChange = async (roleId: string) => {
    setSelectedRole(roleId)
    setErrorMessage(null)

    if (apiBaseUrl) {
      setIsLoading(true)
      try {
        const headers: Record<string, string> = {}
        if (apiKey) headers['X-API-Key'] = apiKey

        const roleParam = roleId === 'all' ? '' : `&role=${roleId}`
        const resp = await fetch(
          `${apiBaseUrl}/v1/playbooks/${runId}/tasks?tenant_id=${tenantId}${roleParam}`,
          { headers }
        )

        if (!resp.ok) {
          const errData = await resp.json()
          throw new Error(errData.detail || 'Failed to fetch tasks')
        }

        const data: RoleTaskListData = await resp.json()
        setTaskData(data)
      } catch (err: unknown) {
        setErrorMessage(err instanceof Error ? err.message : String(err))
      } finally {
        setIsLoading(false)
      }
    } else {
      // Local filtering
      if (roleId === 'all') {
        setTaskData(initialData)
      } else {
        const filteredPending = initialData.pending_tasks.filter((t) => t.role === roleId)
        const filteredCompleted = initialData.completed_tasks.filter((t) => t.role === roleId)
        const hours = filteredPending.reduce((acc, t) => acc + t.estimated_hours, 0)
        setTaskData({
          role: roleId,
          pending_tasks: filteredPending,
          completed_tasks: filteredCompleted,
          total_estimated_hours: hours,
        })
      }
    }
  }

  const pending = taskData.pending_tasks
  const completed = taskData.completed_tasks

  return (
    <div
      data-testid="role-task-view-container"
      className={`rounded-xl border border-slate-800 bg-slate-900 p-5 text-slate-100 shadow-xl ${className}`}
    >
      {/* Header */}
      <div className="mb-4 flex flex-col justify-between gap-3 border-b border-slate-800 pb-4 md:flex-row md:items-center">
        <div>
          <h2 className="text-lg font-bold text-white">Role-Based Compliance Action Checklist</h2>
          <p className="mt-1 text-xs text-slate-400">
            Dispatched deliverables tailored to statutory engineering and compliance roles.
          </p>
        </div>

        <div className="flex items-center gap-4 text-xs font-mono">
          <div>
            <span className="text-slate-400">Pending Tasks: </span>
            <span data-testid="pending-task-count" className="font-bold text-cyan-300">
              {pending.length}
            </span>
          </div>
          <div>
            <span className="text-slate-400">Total Est. Effort: </span>
            <span data-testid="total-estimated-hours" className="font-bold text-amber-300">
              {taskData.total_estimated_hours}h
            </span>
          </div>
        </div>
      </div>

      {/* Role Selector Tabs */}
      <div
        data-testid="role-tab-bar"
        className="mb-5 flex flex-wrap gap-2 border-b border-slate-800 pb-3"
      >
        {CANONICAL_ROLES.map((r) => {
          const isActive = selectedRole === r.id
          return (
            <button
              key={r.id}
              data-testid={`role-tab-${r.id}`}
              type="button"
              onClick={() => handleRoleChange(r.id)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
                isActive
                  ? 'bg-cyan-600 text-white shadow-md shadow-cyan-950'
                  : 'bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white'
              }`}
            >
              {r.label}
            </button>
          )
        })}
      </div>

      {/* Error Alert */}
      {errorMessage && (
        <div
          data-testid="role-task-error-alert"
          className="mb-4 rounded-lg border border-rose-800 bg-rose-950/40 p-3 text-xs text-rose-300"
        >
          {errorMessage}
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div data-testid="role-task-loading" className="py-6 text-center text-xs text-slate-400">
          Routing and filtering deliverables...
        </div>
      )}

      {/* Task List */}
      {!isLoading && (
        <div className="space-y-3">
          {pending.length === 0 && (
            <div
              data-testid="role-task-empty"
              className="rounded-lg border border-dashed border-slate-800 p-8 text-center text-xs text-slate-500"
            >
              No pending tasks dispatched for role <span className="font-semibold text-slate-400">{selectedRole}</span>.
            </div>
          )}

          {pending.map((task) => (
            <div
              key={task.task_id}
              data-testid={`task-item-${task.task_id}`}
              onClick={() => onTaskSelected && onTaskSelected(task)}
              className="flex flex-col justify-between gap-3 rounded-lg border border-slate-800 bg-slate-950/60 p-4 transition-all hover:border-slate-700 hover:bg-slate-950 md:flex-row md:items-center cursor-pointer"
            >
              <div className="flex items-start gap-3">
                <span className="mt-0.5 rounded bg-slate-800 px-2 py-0.5 font-mono text-xs font-bold text-cyan-400">
                  {task.task_id}
                </span>
                <div>
                  <div className="text-sm font-semibold text-white">{task.title}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded bg-indigo-950 px-2 py-0.5 font-mono text-indigo-300 border border-indigo-900">
                      Stage {task.stage}
                    </span>
                    <span className="font-mono text-slate-500">{task.term_reference}</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3 self-end md:self-center">
                <span
                  data-testid={`task-role-badge-${task.task_id}`}
                  className="rounded-full bg-slate-800 px-2.5 py-0.5 text-xs font-medium uppercase tracking-wider text-slate-300 border border-slate-700"
                >
                  {task.role}
                </span>
                <span
                  data-testid={`task-hours-${task.task_id}`}
                  className="rounded bg-amber-950/80 px-2 py-0.5 font-mono text-xs font-bold text-amber-400 border border-amber-900"
                >
                  {task.estimated_hours}h
                </span>
              </div>
            </div>
          ))}

          {/* Completed Tasks section */}
          {completed.length > 0 && (
            <div className="mt-6 border-t border-slate-800 pt-4">
              <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">
                Completed Deliverables ({completed.length})
              </h3>
              <div className="space-y-2 opacity-60">
                {completed.map((task) => (
                  <div
                    key={task.task_id}
                    data-testid={`completed-task-${task.task_id}`}
                    className="flex items-center justify-between rounded border border-slate-800 bg-slate-950/40 p-2 text-xs text-slate-400"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-emerald-400">✓ {task.task_id}</span>
                      <span className="line-through">{task.title}</span>
                    </div>
                    <span className="font-mono">{task.role}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default RoleTaskView
