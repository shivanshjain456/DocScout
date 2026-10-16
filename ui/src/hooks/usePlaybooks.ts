import { useState, useEffect, useCallback, useMemo, useRef } from 'react'

export interface MilestoneItem {
  id: string
  title: string
  role: string
  mandatory?: boolean
  completed?: boolean
  completed_at?: string | null
  evidence_doc_id?: string | null
  notes?: string
}

export interface StageItem {
  number: number
  name: string
  objective: string
  exit_criteria: string[]
  milestones: MilestoneItem[]
}

export interface PlaybookTemplate {
  playbook_id: string
  title: string
  description: string
  domain: string
  total_stages: number
  stages: StageItem[]
}

export interface CompletedMilestoneRecord {
  milestone_id: string
  stage_number: number
  completed_at: string
  evidence_doc_id?: string | null
  notes?: string
}

export interface StageHistoryRecord {
  stage_number: number
  entered_at: string
  exited_at?: string
  status: string
}

export interface PlaybookRun {
  run_id: string
  tenant_id: string
  playbook_id: string
  title: string
  assigned_lead: string
  current_stage: number
  total_stages: number
  status: 'ACTIVE' | 'BLOCKED' | 'COMPLETED'
  stage_data: {
    completed_milestones: CompletedMilestoneRecord[]
    stage_history: StageHistoryRecord[]
  }
  created_at: string
  updated_at: string
}

export interface PlaybookUIPreferences {
  refresh_interval_seconds: number
}

export interface UsePlaybooksOptions {
  runId?: string
  tenantId?: string
  apiBaseUrl?: string
  apiKey?: string
  refreshIntervalSeconds?: number
  initialRun?: PlaybookRun
}

export interface UsePlaybooksResult {
  activeRun: PlaybookRun | null
  templates: PlaybookTemplate[]
  currentStage: StageItem | null
  allStages: StageItem[]
  loading: boolean
  error: string | null
  overallProgressPct: number
  stageProgressPct: number
  isExitCriteriaSatisfied: boolean
  completeMilestone: (
    milestoneId: string,
    notes?: string,
    evidenceDocId?: string
  ) => Promise<boolean>
  promoteStage: (
    targetStage?: number,
    adminOverride?: boolean
  ) => Promise<{ success: boolean; error?: string }>
  selectPlaybook: (playbookId: string) => Promise<string>
  refresh: () => Promise<void>
  exportAuditSummary: () => string
}

export const CANONICAL_TEMPLATES: Record<string, PlaybookTemplate> = {
  'playbook.foundations-30d': {
    playbook_id: 'playbook.foundations-30d',
    title: 'Foundations 30-Day Engineering Decoupling',
    description:
      'Establish decoupled service boundaries, hermetic test fixtures, and modular regulatory controls.',
    domain: 'core-architecture',
    total_stages: 4,
    stages: [
      {
        number: 1,
        name: 'Decouple / Establish',
        objective:
          'Catalog existing monorepo boundaries and inventory regulatory dependency edges.',
        exit_criteria: [
          'Domain interfaces documented with zero circular schema references.',
        ],
        milestones: [
          {
            id: 'M1-1',
            title: 'Map database dependencies and domain boundary edges',
            role: 'sre',
          },
          {
            id: 'M1-2',
            title: 'Draft architectural decoupling ADR and API contracts',
            role: 'developer',
          },
        ],
      },
      {
        number: 2,
        name: 'Bound / Contain',
        objective:
          'Implement architectural bulkheads and isolate critical transaction pathways.',
        exit_criteria: [
          'Zero uncontained cross-boundary database queries detected in CI.',
        ],
        milestones: [
          {
            id: 'M2-1',
            title: 'Enforce service boundary linting and strict package visibility',
            role: 'developer',
          },
          {
            id: 'M2-2',
            title: 'Deploy bulkhead concurrency limits for tenant workloads',
            role: 'sre',
          },
        ],
      },
      {
        number: 3,
        name: 'Automate',
        objective:
          'Deploy continuous compliance verification pipelines and automated policy gates.',
        exit_criteria: [
          'Automated policy verification gate runs on 100% of pull requests.',
        ],
        milestones: [
          {
            id: 'M3-1',
            title: 'Integrate pre-merge compliance check gate in CI',
            role: 'developer',
          },
          {
            id: 'M3-2',
            title: 'Configure synthetic canary transactions with audit telemetry',
            role: 'sre',
          },
        ],
      },
      {
        number: 4,
        name: 'Self-Govern',
        objective:
          'Achieve zero-touch compliance auditing with deterministic provenance records.',
        exit_criteria: [
          'Zero manual audit interventions required for continuous compliance reporting.',
        ],
        milestones: [
          {
            id: 'M4-1',
            title: 'Enable self-healing policy enforcement bots',
            role: 'compliance-officer',
          },
          {
            id: 'M4-2',
            title: 'Certify autonomous compliance reporting dashboard',
            role: 'compliance-officer',
          },
        ],
      },
    ],
  },
  'playbook.ai-assurance': {
    playbook_id: 'playbook.ai-assurance',
    title: 'Algorithmic & AI Model Risk Governance Playbook',
    description:
      'Operationalize SEBI algorithmic trading guidelines and RBI model governance requirements.',
    domain: 'ai-governance',
    total_stages: 4,
    stages: [
      {
        number: 1,
        name: 'Decouple / Establish',
        objective:
          'Establish model inventory, baseline explainability standards, and kill switch mechanisms.',
        exit_criteria: [
          'Complete algorithmic inventory with signed-off model cards.',
        ],
        milestones: [
          {
            id: 'M1-1',
            title: 'Register AI/ML models and data pipelines in catalog',
            role: 'developer',
          },
          {
            id: 'M1-2',
            title: 'Implement hard autonomous kill-switch API endpoints',
            role: 'sre',
          },
        ],
      },
      {
        number: 2,
        name: 'Bound / Contain',
        objective: 'Conduct drift monitoring and bias audits.',
        exit_criteria: ['Bias disparity metric below 1.25 across all sensitive sub-populations.'],
        milestones: [
          {
            id: 'M2-1',
            title: 'Deploy real-time statistical feature drift detection',
            role: 'developer',
          },
          {
            id: 'M2-2',
            title: 'Audit proxy variable correlations against protected attributes',
            role: 'compliance-officer',
          },
        ],
      },
      {
        number: 3,
        name: 'Automate',
        objective: 'Automate continuous adversarial stress-testing in pre-production.',
        exit_criteria: ['100% of prompt injection and evasion benchmarks executed in CI.'],
        milestones: [
          {
            id: 'M3-1',
            title: 'Run automated jailbreak and perturbation stress test suite',
            role: 'security',
          },
        ],
      },
      {
        number: 4,
        name: 'Self-Govern',
        objective: 'Certify AI governance transparency and regulatory disclosures.',
        exit_criteria: ['Signed GSN safety case for autonomous algorithm operations.'],
        milestones: [
          {
            id: 'M4-1',
            title: 'Publish customer-facing AI decision explanation disclosures',
            role: 'legal',
          },
        ],
      },
    ],
  },
}

export const DEFAULT_INITIAL_RUN: PlaybookRun = {
  run_id: 'run-seed-default-01',
  tenant_id: 'default',
  playbook_id: 'playbook.foundations-30d',
  title: 'Foundations 30-Day Engineering Decoupling',
  assigned_lead: 'Engineering Lead & CCO',
  current_stage: 1,
  total_stages: 4,
  status: 'ACTIVE',
  stage_data: {
    completed_milestones: [
      {
        milestone_id: 'M1-1',
        stage_number: 1,
        completed_at: new Date(Date.now() - 3600000).toISOString(),
        notes: 'Initial boundary graph mapped and validated against schema.',
      },
    ],
    stage_history: [
      {
        stage_number: 1,
        entered_at: new Date(Date.now() - 86400000).toISOString(),
        status: 'ACTIVE',
      },
    ],
  },
  created_at: new Date(Date.now() - 86400000).toISOString(),
  updated_at: new Date().toISOString(),
}

export function usePlaybooks(options?: UsePlaybooksOptions): UsePlaybooksResult {
  const {
    runId = 'run-seed-default-01',
    tenantId = 'default',
    apiBaseUrl = '',
    apiKey = '',
    refreshIntervalSeconds = 30,
    initialRun,
  } = options || {}

  const [activeRun, setActiveRun] = useState<PlaybookRun>(
    initialRun || DEFAULT_INITIAL_RUN
  )
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<number | null>(null)

  const template = useMemo(() => {
    return CANONICAL_TEMPLATES[activeRun.playbook_id] || CANONICAL_TEMPLATES['playbook.foundations-30d']
  }, [activeRun.playbook_id])

  const allStages = useMemo(() => {
    const completedSet = new Set(
      activeRun.stage_data.completed_milestones.map((m) => m.milestone_id)
    )
    return template.stages.map((stage) => ({
      ...stage,
      milestones: stage.milestones.map((m) => ({
        ...m,
        completed: completedSet.has(m.id),
      })),
    }))
  }, [template, activeRun.stage_data.completed_milestones])

  const currentStage = useMemo(() => {
    return allStages.find((s) => s.number === activeRun.current_stage) || allStages[0] || null
  }, [allStages, activeRun.current_stage])

  // Calculation of progress percentages
  const overallProgressPct = useMemo(() => {
    const totalMilestones = template.stages.reduce(
      (sum, s) => sum + s.milestones.length,
      0
    )
    if (totalMilestones === 0) return 0
    const completedCount = activeRun.stage_data.completed_milestones.length
    return Math.min(100, Math.round((completedCount / totalMilestones) * 100))
  }, [template, activeRun.stage_data.completed_milestones])

  const stageProgressPct = useMemo(() => {
    if (!currentStage || currentStage.milestones.length === 0) return 0
    const stageCompleted = currentStage.milestones.filter((m) => m.completed).length
    return Math.min(100, Math.round((stageCompleted / currentStage.milestones.length) * 100))
  }, [currentStage])

  const isExitCriteriaSatisfied = useMemo(() => {
    if (!currentStage) return false
    return currentStage.milestones.every((m) => m.completed)
  }, [currentStage])

  const fetchRun = useCallback(async () => {
    if (!apiBaseUrl) return
    try {
      const res = await fetch(
        `${apiBaseUrl}/v1/playbooks/${runId}?tenant_id=${tenantId}`,
        {
          headers: {
            'Content-Type': 'application/json',
            ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
          },
        }
      )
      if (res.ok) {
        const data: PlaybookRun = await res.json()
        setActiveRun(data)
        setError(null)
      } else {
        setError(`Failed to fetch playbook run: HTTP ${res.status}`)
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Network error'
      setError(message)
    }
  }, [apiBaseUrl, runId, tenantId, apiKey])

  useEffect(() => {
    if (!apiBaseUrl) return
    fetchRun()
    if (refreshIntervalSeconds > 0) {
      const intervalMs = refreshIntervalSeconds * 1000
      timerRef.current = window.setInterval(fetchRun, intervalMs)
      return () => {
        if (timerRef.current) clearInterval(timerRef.current)
      }
    }
  }, [fetchRun, refreshIntervalSeconds, apiBaseUrl])

  const completeMilestone = useCallback(
    async (
      milestoneId: string,
      notes: string = '',
      evidenceDocId: string | null = null
    ): Promise<boolean> => {
      // Optimistic update
      const nowIso = new Date().toISOString()
      const prevRun = activeRun
      const isAlreadyCompleted = activeRun.stage_data.completed_milestones.some(
        (m) => m.milestone_id === milestoneId
      )

      let updatedCompleted: CompletedMilestoneRecord[]
      if (isAlreadyCompleted) {
        updatedCompleted = activeRun.stage_data.completed_milestones.filter(
          (m) => m.milestone_id !== milestoneId
        )
      } else {
        updatedCompleted = [
          ...activeRun.stage_data.completed_milestones,
          {
            milestone_id: milestoneId,
            stage_number: activeRun.current_stage,
            completed_at: nowIso,
            notes,
            evidence_doc_id: evidenceDocId,
          },
        ]
      }

      const updatedRun: PlaybookRun = {
        ...activeRun,
        updated_at: nowIso,
        stage_data: {
          ...activeRun.stage_data,
          completed_milestones: updatedCompleted,
        },
      }
      setActiveRun(updatedRun)

      if (apiBaseUrl) {
        try {
          const res = await fetch(
            `${apiBaseUrl}/v1/playbooks/${activeRun.run_id}/milestones/${milestoneId}?tenant_id=${tenantId}`,
            {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
              },
              body: JSON.stringify({
                notes,
                evidence_doc_id: evidenceDocId,
              }),
            }
          )
          if (!res.ok) {
            // Revert on error
            setActiveRun(prevRun)
            return false
          }
        } catch {
          setActiveRun(prevRun)
          return false
        }
      }
      return true
    },
    [activeRun, apiBaseUrl, apiKey, tenantId]
  )

  const promoteStage = useCallback(
    async (
      targetStage?: number,
      adminOverride: boolean = false
    ): Promise<{ success: boolean; error?: string }> => {
      const nextStage = targetStage || activeRun.current_stage + 1
      if (nextStage > activeRun.total_stages) {
        return { success: false, error: 'Playbook is already in the final stage' }
      }

      if (!isExitCriteriaSatisfied && !adminOverride) {
        return {
          success: false,
          error:
            'Stage exit criteria not satisfied. Complete all stage milestones or provide admin override.',
        }
      }

      const nowIso = new Date().toISOString()
      const updatedHistory: StageHistoryRecord[] = [
        ...activeRun.stage_data.stage_history.map((h) =>
          h.stage_number === activeRun.current_stage
            ? { ...h, exited_at: nowIso, status: 'COMPLETED' }
            : h
        ),
        {
          stage_number: nextStage,
          entered_at: nowIso,
          status: 'ACTIVE',
        },
      ]

      const updatedRun: PlaybookRun = {
        ...activeRun,
        current_stage: nextStage,
        status: nextStage === activeRun.total_stages ? 'COMPLETED' : 'ACTIVE',
        updated_at: nowIso,
        stage_data: {
          ...activeRun.stage_data,
          stage_history: updatedHistory,
        },
      }

      if (apiBaseUrl) {
        try {
          const res = await fetch(
            `${apiBaseUrl}/v1/playbooks/${activeRun.run_id}/promote?tenant_id=${tenantId}`,
            {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
              },
              body: JSON.stringify({
                target_stage: nextStage,
                admin_override: adminOverride,
              }),
            }
          )
          if (!res.ok) {
            const errData = await res.json().catch(() => ({}))
            return {
              success: false,
              error: errData.detail || `Promotion rejected with HTTP ${res.status}`,
            }
          }
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : 'Network failure during stage promotion'
          return { success: false, error: message }
        }
      }

      setActiveRun(updatedRun)
      return { success: true }
    },
    [activeRun, isExitCriteriaSatisfied, apiBaseUrl, apiKey, tenantId]
  )

  const selectPlaybook = useCallback(
    async (playbookId: string): Promise<string> => {
      const tmpl = CANONICAL_TEMPLATES[playbookId]
      if (!tmpl) return activeRun.run_id

      const newRunId = `run-${playbookId.replace('playbook.', '')}-${Date.now().toString(36)}`
      const newRun: PlaybookRun = {
        run_id: newRunId,
        tenant_id: tenantId,
        playbook_id: tmpl.playbook_id,
        title: tmpl.title,
        assigned_lead: 'Engineering Lead & CCO',
        current_stage: 1,
        total_stages: tmpl.total_stages,
        status: 'ACTIVE',
        stage_data: {
          completed_milestones: [],
          stage_history: [
            {
              stage_number: 1,
              entered_at: new Date().toISOString(),
              status: 'ACTIVE',
            },
          ],
        },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      setActiveRun(newRun)
      return newRunId
    },
    [tenantId, activeRun.run_id]
  )

  const exportAuditSummary = useCallback((): string => {
    const lines = [
      `# Playbook Audit Progress Report`,
      ``,
      `- **Playbook ID:** ${activeRun.playbook_id}`,
      `- **Title:** ${activeRun.title}`,
      `- **Tenant ID:** ${activeRun.tenant_id}`,
      `- **Current Stage:** Stage ${activeRun.current_stage} of ${activeRun.total_stages}`,
      `- **Overall Completion:** ${overallProgressPct}%`,
      `- **Status:** ${activeRun.status}`,
      `- **Generated:** ${new Date().toISOString()}`,
      ``,
      `## Milestone Progression`,
      ``,
    ]

    for (const stage of allStages) {
      lines.push(`### Stage ${stage.number}: ${stage.name}`)
      lines.push(`Objective: ${stage.objective}`)
      lines.push(``)
      for (const m of stage.milestones) {
        const marker = m.completed ? '[x]' : '[ ]'
        lines.push(`- ${marker} **[${m.role.toUpperCase()}]** ${m.title} (${m.id})`)
      }
      lines.push(``)
    }

    return lines.join('\n')
  }, [activeRun, allStages, overallProgressPct])

  return {
    activeRun,
    templates: Object.values(CANONICAL_TEMPLATES),
    currentStage,
    allStages,
    loading,
    error,
    overallProgressPct,
    stageProgressPct,
    isExitCriteriaSatisfied,
    completeMilestone,
    promoteStage,
    selectPlaybook,
    refresh: fetchRun,
    exportAuditSummary,
  }
}
