import { useState, useEffect } from 'react'

export interface TaxonomyTerm {
  id: string
  term: string
  definition: string
  layer?: string
  source?: string
  aliases?: string[]
  related?: string[]
}

export type TaxonomyDictionary = Record<string, TaxonomyTerm>

export interface UseTaxonomyDictionaryResult {
  dictionary: TaxonomyDictionary
  loading: boolean
  error: string | null
  lookupTerm: (token: string) => TaxonomyTerm | undefined
  termsList: TaxonomyTerm[]
}

// In-memory module-level cache so dictionary is loaded only once per application lifecycle
let cachedDictionary: TaxonomyDictionary | null = null
let cachedLookupMap: Map<string, TaxonomyTerm> | null = null
let cachedTermsList: TaxonomyTerm[] | null = null

// Seed fallback terms for guaranteed offline / test execution
const FALLBACK_SEED_TERMS: TaxonomyTerm[] = [
  {
    id: 'digital-lending',
    term: 'Digital Lending',
    definition: 'A remote and automated lending process, largely by use of seamless digital technologies.',
    layer: 'physical-and-regulated',
    source: 'RBI Guidelines 2022',
    aliases: ['DL'],
    related: ['first-loss-default-guarantee', 'commercial_bank', 'nbfc'],
  },
  {
    id: 'first-loss-default-guarantee',
    term: 'First Loss Default Guarantee',
    definition: 'Contractual arrangement between Regulated Entity and Lending Service Provider to compensate credit losses up to a ceiling.',
    layer: 'physical-and-regulated',
    source: 'RBI FLDG Framework 2023',
    aliases: ['FLDG'],
    related: ['digital-lending', 'regulated_entity'],
  },
  {
    id: 'regulated_entity',
    term: 'Regulated Entity',
    definition: 'All Commercial Banks, Primary Urban Co-operative Banks, and Non-Banking Financial Companies.',
    layer: 'physical-and-regulated',
    source: 'RBI Master Directions',
    aliases: ['RE'],
    related: ['commercial_bank', 'nbfc'],
  },
  {
    id: 'nbfc',
    term: 'Non-Banking Financial Company',
    definition: 'Financial institution registered under the Companies Act engaged in lending and investing.',
    layer: 'physical-and-regulated',
    source: 'RBI Act 1934',
    aliases: ['NBFC'],
    related: ['regulated_entity', 'commercial_bank'],
  },
  {
    id: 'commercial_bank',
    term: 'Commercial Bank',
    definition: 'Scheduled commercial banking institution regulated under the Banking Regulation Act 1949.',
    layer: 'physical-and-regulated',
    source: 'Banking Regulation Act',
    aliases: ['Scheduled Commercial Bank'],
    related: ['regulated_entity'],
  },
]

function buildLookupMaps(dict: TaxonomyDictionary) {
  const map = new Map<string, TaxonomyTerm>()
  const list = Object.values(dict)

  for (const item of list) {
    if (!item.term) continue
    map.set(item.term.toLowerCase(), item)
    if (item.id) {
      map.set(item.id.toLowerCase(), item)
    }
    if (item.aliases) {
      for (const alias of item.aliases) {
        if (alias) {
          map.set(alias.toLowerCase(), item)
        }
      }
    }
  }

  // Sort by token length descending for greedy substring matching
  list.sort((a, b) => b.term.length - a.term.length)

  return { map, list }
}

export function useTaxonomyDictionary(): UseTaxonomyDictionaryResult {
  const [dictionary, setDictionary] = useState<TaxonomyDictionary>(cachedDictionary || {})
  const [loading, setLoading] = useState<boolean>(!cachedDictionary)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (cachedDictionary) {
      return
    }

    let active = true

    async function loadDictionary() {
      try {
        // 1. Try public API endpoint first
        let res = await fetch('/v1/taxonomy/dictionary')
        if (!res.ok) {
          // 2. Fall back to static bundle
          res = await fetch('/taxonomy-dictionary.json')
        }

        if (!res.ok) {
          throw new Error(`Failed to load taxonomy dictionary (HTTP ${res.status})`)
        }

        const data: TaxonomyDictionary = await res.json()
        if (active) {
          cachedDictionary = data
          const { map, list } = buildLookupMaps(data)
          cachedLookupMap = map
          cachedTermsList = list
          setDictionary(data)
          setLoading(false)
        }
      } catch (err: unknown) {
        if (active) {
          // Graceful fallback to seed terms on any failure
          const fallbackDict: TaxonomyDictionary = {}
          for (const t of FALLBACK_SEED_TERMS) {
            fallbackDict[t.id] = t
          }
          cachedDictionary = fallbackDict
          const { map, list } = buildLookupMaps(fallbackDict)
          cachedLookupMap = map
          cachedTermsList = list
          setDictionary(fallbackDict)
          setLoading(false)
          setError(err instanceof Error ? err.message : String(err))
        }
      }
    }

    loadDictionary()

    return () => {
      active = false
    }
  }, [])

  const lookupTerm = (token: string): TaxonomyTerm | undefined => {
    if (!token) return undefined
    const normalized = token.trim().toLowerCase()
    if (cachedLookupMap) {
      return cachedLookupMap.get(normalized)
    }
    return undefined
  }

  return {
    dictionary,
    loading,
    error,
    lookupTerm,
    termsList: cachedTermsList || Object.values(dictionary),
  }
}
