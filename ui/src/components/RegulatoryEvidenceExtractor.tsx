import React, { useState } from 'react';

export interface StatutoryParameter {
  id: string;
  document_id: string;
  parameter_name: string;
  parameter_type: string;
  numeric_value: number;
  unit: string;
  normalized_value: number;
  normalized_unit: string;
  comparison_operator: string;
  statutory_context: string;
  threshold_ceiling?: number | null;
  section_reference?: string | null;
  char_start?: number | null;
  char_end?: number | null;
  confidence_score: number;
}

const SAMPLE_CIRCULARS = [
  {
    title: 'RBI Master Direction - Digital Lending (2022/2026)',
    text: `Section 4.1. Borrowers shall be provided a cooling-off period of not less than 3 days for loans having tenor of 7 days or more, and 1 day for loans having tenor less than 7 days.\nClause 6.3. Any Regulated Entity failing to adhere to data localization shall attract a penalty of Rs. 10 lakh per occurrence, up to a maximum of Rs 1 crore.\nSection 8.2. REs must have a minimum net worth of Rs 100 crore before engaging in third-party LSP underwriting.`,
  },
  {
    title: 'SEBI (LODR) Regulation 30 - Materiality Thresholds',
    text: `Regulation 30(4). The listed entity shall disclose any event or information within 24 hours of occurrence, or within 30 minutes following the board meeting closure.\nClause 12(b). Materiality threshold is defined as an impact exceeding 2% of turnover or 5% of net worth, or an amount exceeding INR 50 crore, whichever is lower.\nAnnexure I. In case of continuing default, penalty of Rs. 25,000 per day shall apply not exceeding INR 25 lakh.`,
  },
  {
    title: 'RBI Basel III Capital Adequacy Directions',
    text: `Paragraph 3.2. Commercial banks must maintain a minimum CRAR of 9.0% on an ongoing basis.\nPara 3.4. Minimum Tier 1 capital ratio shall be 7.0%, while minimum common equity tier 1 ratio shall be 5.5%.\nSchedule B. Collateral haircuts: sovereign debt haircut of 0.5%, corporate bonds haircut of 15%, equity haircut not less than 25%.`,
  },
];

export const RegulatoryEvidenceExtractor: React.FC = () => {
  const [inputText, setInputText] = useState(SAMPLE_CIRCULARS[0].text);
  const [parameters, setParameters] = useState<StatutoryParameter[]>([]);
  const [selectedType, setSelectedType] = useState<string>('ALL');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExtract = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch('/v1/compliance/extract-parameters', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer test-key',
        },
        body: JSON.stringify({
          text: inputText,
          document_id: 'doc-console-sample',
        }),
      });

      if (!resp.ok) {
        throw new Error(`Extraction failed: ${resp.statusText}`);
      }

      const data = await resp.json();
      setParameters(data.parameters || []);
    } catch (err: any) {
      setError(err.message || 'Error executing numerical evidence extraction');
    } finally {
      setLoading(false);
    }
  };

  const filtered = selectedType === 'ALL'
    ? parameters
    : parameters.filter((p) => p.parameter_type === selectedType);

  const availableTypes = ['ALL', ...Array.from(new Set(parameters.map((p) => p.parameter_type)))];

  const formatNormalized = (val: number, unit: string) => {
    if (unit === 'INR') {
      return `₹${val.toLocaleString('en-IN')}`;
    }
    if (unit === 'ratio') {
      return `${(val * 100).toFixed(2)}% (${val})`;
    }
    if (unit === 'days') {
      return `${val.toFixed(1)} days`;
    }
    return `${val} ${unit}`;
  };

  return (
    <div className="p-6 bg-slate-900 text-slate-100 rounded-xl shadow-xl border border-slate-800">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <span className="p-1.5 rounded-lg bg-emerald-500/20 text-emerald-400">#</span>
            Numerical Regulatory Evidence Extractor
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Quantitative statutory parameter parser for penalties, filing windows, net worth thresholds and regulatory ratios
          </p>
        </div>
        <span className="px-3 py-1 bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 text-xs font-semibold rounded-full">
          FEAT-026 Verified
        </span>
      </div>

      <div className="mt-4">
        <label className="text-xs font-semibold text-slate-400 block mb-1">
          Preset Circular Text
        </label>
        <div className="flex flex-wrap gap-2 mb-3">
          {SAMPLE_CIRCULARS.map((sc, idx) => (
            <button
              key={idx}
              onClick={() => setInputText(sc.text)}
              className="px-2.5 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
            >
              {sc.title}
            </button>
          ))}
        </div>

        <textarea
          rows={5}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          placeholder="Paste regulatory circular prose or tables containing monetary penalties, time limits, or ratios..."
          className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
        />

        <div className="flex justify-end mt-2">
          <button
            onClick={handleExtract}
            disabled={loading || !inputText.trim()}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-medium rounded-lg shadow transition flex items-center gap-2"
          >
            {loading ? 'Extracting Parameters...' : 'Extract Statutory Parameters'}
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-4 p-3 bg-red-950/60 border border-red-800 text-red-300 text-xs rounded-lg">
          {error}
        </div>
      )}

      {parameters.length > 0 && (
        <div className="mt-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-slate-200">
              Extracted Statutory Evidence ({filtered.length} of {parameters.length})
            </h3>
            <div className="flex items-center gap-1">
              <span className="text-xs text-slate-500 mr-2">Filter Type:</span>
              {availableTypes.map((t) => (
                <button
                  key={t}
                  onClick={() => setSelectedType(t)}
                  className={`px-2 py-0.5 text-xs rounded ${
                    selectedType === t
                      ? 'bg-emerald-500 text-slate-950 font-bold'
                      : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 max-h-96 overflow-y-auto pr-1">
            {filtered.map((param) => (
              <div
                key={param.id}
                className="p-3 bg-slate-950/80 border border-slate-800 rounded-lg hover:border-slate-700 transition"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-slate-200 text-xs">
                        {param.parameter_name}
                      </span>
                      {param.section_reference && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                          {param.section_reference}
                        </span>
                      )}
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 uppercase font-mono">
                        {param.parameter_type}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-1 italic font-serif">
                      "{param.statutory_context}"
                    </p>
                  </div>
                  <div className="text-right flex flex-col items-end">
                    <span className="text-xs font-mono font-bold text-emerald-400">
                      {param.comparison_operator.toUpperCase()} {param.numeric_value} {param.unit}
                    </span>
                    <span className="text-[10px] font-mono text-slate-400 mt-0.5">
                      Base: {formatNormalized(param.normalized_value, param.normalized_unit)}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default RegulatoryEvidenceExtractor;
