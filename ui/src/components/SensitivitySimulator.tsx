import React, { useId, useState, useMemo, useCallback } from "react";

export interface ScenarioPoint {
  step: number;
  variable: string;
  input_value: number;
  delta_percentage: number;
  computed_value: number;
  status?: "COMPLIANT" | "WARNING" | "BREACH" | null;
  margin?: number | null;
}

export interface SensitivityResult {
  variable: string;
  description?: string | null;
  baseline_input: number;
  partial_derivative: number;
  elasticity: number;
  direction: "positive" | "negative" | "neutral";
  impact_rank: number;
  breach_boundary_value?: number | null;
}

export interface StressScenarioResult {
  name: string;
  description: string;
  inputs: Record<string, number>;
  computed_value: number;
  delta_percentage_from_baseline: number;
  status?: "COMPLIANT" | "WARNING" | "BREACH" | null;
}

export interface SimulationResponse {
  formula_id: string;
  formula_name: string;
  expression: string;
  unit: string;
  baseline_value: number;
  baseline_status?: "COMPLIANT" | "WARNING" | "BREACH" | null;
  statutory_threshold?: string | null;
  sensitivity_gradients: Record<string, number>;
  elasticities: Record<string, number>;
  sensitivities: SensitivityResult[];
  scenario_curves: Record<string, ScenarioPoint[]>;
  stress_tests: StressScenarioResult[];
  latency_ms: number;
}

export interface SensitivitySimulatorProps {
  apiKey?: string;
  initialFormulaId?: string;
  onSimulationChange?: (res: SimulationResponse) => void;
}

interface FormulaPreset {
  id: string;
  name: string;
  expression: string;
  unit: string;
  statutoryThreshold: string;
  thresholdVal: number;
  thresholdOp: ">=" | "<=";
  defaultInputs: Record<string, number>;
  inputRanges: Record<string, { min: number; max: number; step: number; unit: string }>;
  descriptions: Record<string, string>;
  stressPresets: { name: string; description: string; multipliers: Record<string, number> }[];
}

const FORMULA_PRESETS: Record<string, FormulaPreset> = {
  crar: {
    id: "crar",
    name: "Capital to Risk-Weighted Assets Ratio (CRAR)",
    expression: "CRAR = (tier1_capital + tier2_capital) / risk_weighted_assets",
    unit: "ratio",
    statutoryThreshold: ">= 0.15 (15.0% for NBFC-SI / 9.0% Banks)",
    thresholdVal: 0.15,
    thresholdOp: ">=",
    defaultInputs: {
      tier1_capital: 160.0,
      tier2_capital: 40.0,
      risk_weighted_assets: 1200.0,
    },
    inputRanges: {
      tier1_capital: { min: 50.0, max: 400.0, step: 5.0, unit: "Cr" },
      tier2_capital: { min: 0.0, max: 150.0, step: 2.0, unit: "Cr" },
      risk_weighted_assets: { min: 500.0, max: 2500.0, step: 25.0, unit: "Cr" },
    },
    descriptions: {
      tier1_capital: "Core Equity Tier 1 capital base",
      tier2_capital: "Supplementary Tier 2 subordinated debt & provisions",
      risk_weighted_assets: "Total risk-weighted assets across credit, market & operational risk",
    },
    stressPresets: [
      {
        name: "RBI Moderate Stress",
        description: "5% Tier 1 erosion and 10% RWA growth",
        multipliers: { tier1_capital: 0.95, tier2_capital: 0.98, risk_weighted_assets: 1.10 },
      },
      {
        name: "RBI Severe Macro Downturn",
        description: "15% Tier 1 credit write-downs and 25% RWA ratings downgrade",
        multipliers: { tier1_capital: 0.85, tier2_capital: 0.90, risk_weighted_assets: 1.25 },
      },
    ],
  },
  lcr: {
    id: "lcr",
    name: "Liquidity Coverage Ratio (LCR)",
    expression: "LCR = hqla / net_cash_outflows",
    unit: "ratio",
    statutoryThreshold: ">= 1.00 (100.0%)",
    thresholdVal: 1.0,
    thresholdOp: ">=",
    defaultInputs: {
      hqla: 550.0,
      net_cash_outflows: 480.0,
    },
    inputRanges: {
      hqla: { min: 100.0, max: 1200.0, step: 10.0, unit: "Cr" },
      net_cash_outflows: { min: 100.0, max: 1200.0, step: 10.0, unit: "Cr" },
    },
    descriptions: {
      hqla: "Stock of unencumbered High-Quality Liquid Assets (Cash & G-Secs)",
      net_cash_outflows: "Total net stressed cash outflows over 30 days horizon",
    },
    stressPresets: [
      {
        name: "Idiosyncratic 30-Day Run",
        description: "10% HQLA haircut and 25% deposit runoff spike",
        multipliers: { hqla: 0.90, net_cash_outflows: 1.25 },
      },
      {
        name: "Systemic Liquidity Freeze",
        description: "25% HQLA market valuation collapse and 40% outflow surge",
        multipliers: { hqla: 0.75, net_cash_outflows: 1.40 },
      },
    ],
  },
  "leverage-ratio": {
    id: "leverage-ratio",
    name: "Basel III Leverage Ratio",
    expression: "LeverageRatio = tier1_capital / total_exposure",
    unit: "ratio",
    statutoryThreshold: ">= 0.035 (3.5%)",
    thresholdVal: 0.035,
    thresholdOp: ">=",
    defaultInputs: {
      tier1_capital: 120.0,
      total_exposure: 2800.0,
    },
    inputRanges: {
      tier1_capital: { min: 50.0, max: 300.0, step: 5.0, unit: "Cr" },
      total_exposure: { min: 1000.0, max: 6000.0, step: 50.0, unit: "Cr" },
    },
    descriptions: {
      tier1_capital: "Eligible Tier 1 capital",
      total_exposure: "Total on- and off-balance sheet leverage exposure measure",
    },
    stressPresets: [
      {
        name: "Off-Balance Sheet Surge",
        description: "20% surge in contingent credit commitments",
        multipliers: { tier1_capital: 1.0, total_exposure: 1.20 },
      },
    ],
  },
  sci: {
    id: "sci",
    name: "Software Carbon Intensity (SCI)",
    expression: "SCI = (E * I + M) / R",
    unit: "gCO2eq / unit",
    statutoryThreshold: "<= 50.0 gCO2eq",
    thresholdVal: 50.0,
    thresholdOp: "<=",
    defaultInputs: {
      E: 12.5,
      I: 350.0,
      M: 800.0,
      R: 120.0,
    },
    inputRanges: {
      E: { min: 1.0, max: 50.0, step: 0.5, unit: "kWh" },
      I: { min: 50.0, max: 800.0, step: 10.0, unit: "gCO2eq/kWh" },
      M: { min: 100.0, max: 3000.0, step: 50.0, unit: "gCO2eq" },
      R: { min: 10.0, max: 500.0, step: 5.0, unit: "units" },
    },
    descriptions: {
      E: "Energy consumed by workload in kWh",
      I: "Carbon intensity of grid electricity",
      M: "Embodied hardware emissions allocated to run",
      R: "Functional units processed (requests, transactions)",
    },
    stressPresets: [
      {
        name: "Peak Grid Brownout",
        description: "30% energy surge and 20% grid carbon intensity spike",
        multipliers: { E: 1.30, I: 1.20, M: 1.0, R: 1.0 },
      },
    ],
  },
};

export const SensitivitySimulator: React.FC<SensitivitySimulatorProps> = ({
  apiKey,
  initialFormulaId = "crar",
  onSimulationChange,
}) => {
  const [selectedFormulaId, setSelectedFormulaId] = useState<string>(initialFormulaId);
  const activePreset = FORMULA_PRESETS[selectedFormulaId] || FORMULA_PRESETS.crar;

  const [inputs, setInputs] = useState<Record<string, number>>(activePreset.defaultInputs);
  const [activeCurveVar, setActiveCurveVar] = useState<string>(
    Object.keys(activePreset.defaultInputs)[0]
  );
  const [backendData, setBackendData] = useState<SimulationResponse | null>(null);
  const [isSimulating, setIsSimulating] = useState<boolean>(false);
  const [activePresetName, setActivePresetName] = useState<string | null>(null);
  const componentInstanceId = useId();

  // Local instant calculation fallback when offline/pre-fetch
  const localComputedValue = useMemo(() => {
    try {
      if (selectedFormulaId === "crar") {
        const t1 = inputs.tier1_capital || 0;
        const t2 = inputs.tier2_capital || 0;
        const rwa = inputs.risk_weighted_assets || 1;
        return (t1 + t2) / rwa;
      } else if (selectedFormulaId === "lcr") {
        const hqla = inputs.hqla || 0;
        const out = inputs.net_cash_outflows || 1;
        return hqla / out;
      } else if (selectedFormulaId === "leverage-ratio") {
        const t1 = inputs.tier1_capital || 0;
        const exp = inputs.total_exposure || 1;
        return t1 / exp;
      } else if (selectedFormulaId === "sci") {
        const e = inputs.E || 0;
        const i = inputs.I || 0;
        const m = inputs.M || 0;
        const r = inputs.R || 1;
        return (e * i + m) / r;
      }
    } catch {
      return 0;
    }
    return 0;
  }, [selectedFormulaId, inputs]);

  // Determine compliance status
  const currentStatus: "COMPLIANT" | "WARNING" | "BREACH" = useMemo(() => {
    const val = localComputedValue;
    const thresh = activePreset.thresholdVal;
    const op = activePreset.thresholdOp;
    if (op === ">=") {
      if (val < thresh) return "BREACH";
      if (val < thresh * 1.05) return "WARNING";
      return "COMPLIANT";
    } else {
      if (val > thresh) return "BREACH";
      if (val > thresh * 0.95) return "WARNING";
      return "COMPLIANT";
    }
  }, [localComputedValue, activePreset]);

  // Execute server-side sensitivity simulation
  const fetchSimulation = useCallback(
    async (currentInputs: Record<string, number>) => {
      setIsSimulating(true);
      try {
        const headers: Record<string, string> = { "Content-Type": "application/json" };
        if (apiKey) {
          headers["Authorization"] = `Bearer ${apiKey}`;
        }
        const resp = await fetch("/v1/compliance/simulate", {
          method: "POST",
          headers,
          body: JSON.stringify({
            formula_id: selectedFormulaId,
            base_inputs: currentInputs,
            sweep_percentage_range: 0.25,
            sweep_steps: 11,
          }),
        });
        if (resp.ok) {
          const data: SimulationResponse = await resp.json();
          setBackendData(data);
          if (onSimulationChange) {
            onSimulationChange(data);
          }
        }
      } catch (err) {
        console.warn("Server simulation fetch bypassed:", err);
      } finally {
        setIsSimulating(false);
      }
    },
    [selectedFormulaId, apiKey, onSimulationChange]
  );

  // Switch formula
  const handleSelectFormula = (fId: string) => {
    setSelectedFormulaId(fId);
    const newPreset = FORMULA_PRESETS[fId] || FORMULA_PRESETS.crar;
    setInputs(newPreset.defaultInputs);
    setActiveCurveVar(Object.keys(newPreset.defaultInputs)[0]);
    setActivePresetName(null);
    fetchSimulation(newPreset.defaultInputs);
  };

  // Slider change handler
  const handleInputChange = (varName: string, val: number) => {
    const nextInputs = { ...inputs, [varName]: val };
    setInputs(nextInputs);
    setActivePresetName(null);
  };

  // Apply Stress Preset
  const handleApplyPreset = (preset: { name: string; multipliers: Record<string, number> }) => {
    setActivePresetName(preset.name);
    const updated: Record<string, number> = {};
    for (const [k, baseVal] of Object.entries(activePreset.defaultInputs)) {
      const mult = preset.multipliers[k] ?? 1.0;
      updated[k] = Math.round(baseVal * mult * 100) / 100;
    }
    setInputs(updated);
    fetchSimulation(updated);
  };

  // Reset to default
  const handleReset = () => {
    setInputs(activePreset.defaultInputs);
    setActivePresetName(null);
    fetchSimulation(activePreset.defaultInputs);
  };

  // Synthetic or backend curve points
  const curvePoints = useMemo(() => {
    if (backendData?.scenario_curves[activeCurveVar]) {
      return backendData.scenario_curves[activeCurveVar];
    }
    // Fallback client curve generator (-25% to +25%)
    const baseVal = inputs[activeCurveVar] || 1;
    const pts: ScenarioPoint[] = [];
    for (let i = 0; i <= 10; i++) {
      const deltaPct = -0.25 + i * 0.05;
      const simX = Math.max(0.1, baseVal * (1 + deltaPct));
      const simInputs = { ...inputs, [activeCurveVar]: simX };
      let simOut = 0;
      if (selectedFormulaId === "crar") {
        simOut = (simInputs.tier1_capital + simInputs.tier2_capital) / simInputs.risk_weighted_assets;
      } else if (selectedFormulaId === "lcr") {
        simOut = simInputs.hqla / simInputs.net_cash_outflows;
      } else if (selectedFormulaId === "leverage-ratio") {
        simOut = simInputs.tier1_capital / simInputs.total_exposure;
      } else if (selectedFormulaId === "sci") {
        simOut = (simInputs.E * simInputs.I + simInputs.M) / simInputs.R;
      }
      pts.push({
        step: i + 1,
        variable: activeCurveVar,
        input_value: simX,
        delta_percentage: deltaPct * 100,
        computed_value: simOut,
      });
    }
    return pts;
  }, [backendData, activeCurveVar, inputs, selectedFormulaId]);

  // Compute SVG plotting bounds
  const svgBounds = useMemo(() => {
    if (!curvePoints || curvePoints.length === 0) return { minX: 0, maxX: 1, minY: 0, maxY: 1 };
    const xVals = curvePoints.map((p) => p.input_value);
    const yVals = curvePoints.map((p) => p.computed_value);
    const minX = Math.min(...xVals);
    const maxX = Math.max(...xVals);
    const minY = Math.min(...yVals, activePreset.thresholdVal * 0.8);
    const maxY = Math.max(...yVals, activePreset.thresholdVal * 1.2);
    return { minX, maxX, minY, maxY };
  }, [curvePoints, activePreset]);

  // Generate SVG path data
  const svgPathData = useMemo(() => {
    if (!curvePoints || curvePoints.length < 2) return "";
    const { minX, maxX, minY, maxY } = svgBounds;
    const width = 460;
    const height = 180;
    const spanX = maxX - minX || 1;
    const spanY = maxY - minY || 1;

    return curvePoints
      .map((p, idx) => {
        const x = 30 + ((p.input_value - minX) / spanX) * (width - 40);
        const y = height - 20 - ((p.computed_value - minY) / spanY) * (height - 40);
        return `${idx === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(" ");
  }, [curvePoints, svgBounds]);

  const thresholdY = useMemo(() => {
    const { minY, maxY } = svgBounds;
    const height = 180;
    const spanY = maxY - minY || 1;
    return height - 20 - ((activePreset.thresholdVal - minY) / spanY) * (height - 40);
  }, [svgBounds, activePreset]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "20px",
        padding: "24px",
        borderRadius: "12px",
        backgroundColor: "#0f172a",
        color: "#f8fafc",
        fontFamily: "Inter, system-ui, -apple-system, sans-serif",
        boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.4)",
        maxWidth: "960px",
        margin: "0 auto",
      }}
    >
      {/* Header & Formula Selector */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
          borderBottom: "1px solid #1e293b",
          paddingBottom: "16px",
        }}
      >
        <div>
          <h2 style={{ margin: "0 0 4px 0", fontSize: "1.25rem", fontWeight: 700, color: "#38bdf8" }}>
            Compliance &ldquo;What-If&rdquo; Sensitivity Simulator
          </h2>
          <div style={{ fontSize: "0.85rem", color: "#94a3b8" }}>
            Interactive partial derivatives &amp; statutory stress testing engine
          </div>
        </div>

        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <label
            htmlFor={`formula-select-${componentInstanceId}`}
            style={{ fontSize: "0.85rem", color: "#94a3b8", fontWeight: 500 }}
          >
            Formula:
          </label>
          <select
            id={`formula-select-${componentInstanceId}`}
            value={selectedFormulaId}
            onChange={(e) => handleSelectFormula(e.target.value)}
            style={{
              padding: "6px 12px",
              borderRadius: "6px",
              backgroundColor: "#1e293b",
              color: "#f8fafc",
              border: "1px solid #334155",
              fontSize: "0.85rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            <option value="crar">CRAR (Capital Adequacy)</option>
            <option value="lcr">LCR (Liquidity Coverage)</option>
            <option value="leverage-ratio">Basel III Leverage Ratio</option>
            <option value="sci">Software Carbon Intensity (SCI)</option>
          </select>
        </div>
      </div>

      {/* Formula Expression Card */}
      <div
        style={{
          padding: "12px 16px",
          backgroundColor: "#1e293b",
          borderRadius: "8px",
          borderLeft: "4px solid #38bdf8",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "10px",
        }}
      >
        <div>
          <div style={{ fontSize: "0.8rem", textTransform: "uppercase", color: "#64748b", fontWeight: 700 }}>
            {activePreset.name}
          </div>
          <code style={{ fontSize: "1rem", color: "#e2e8f0", fontWeight: 600, fontFamily: "monospace" }}>
            {activePreset.expression}
          </code>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: "0.75rem", color: "#64748b" }}>Statutory Floor/Ceiling:</div>
          <div style={{ fontSize: "0.85rem", fontWeight: 700, color: "#facc15" }}>
            {activePreset.statutoryThreshold}
          </div>
        </div>
      </div>

      {/* Main Grid: Controls & Real-Time Output */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))",
          gap: "24px",
        }}
      >
        {/* Left Column: Sliders */}
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ margin: 0, fontSize: "0.95rem", color: "#cbd5e1", fontWeight: 600 }}>
              Balance Sheet &amp; Operational Inputs
            </h3>
            <button
              onClick={handleReset}
              style={{
                fontSize: "0.75rem",
                padding: "3px 8px",
                borderRadius: "4px",
                backgroundColor: "#334155",
                color: "#e2e8f0",
                border: "none",
                cursor: "pointer",
              }}
            >
              Reset Inputs
            </button>
          </div>

          {Object.entries(activePreset.defaultInputs).map(([varName, baseVal]) => {
            const range = activePreset.inputRanges[varName] || {
              min: 0,
              max: baseVal * 3,
              step: 1,
              unit: "",
            };
            const currentVal = inputs[varName] ?? baseVal;
            const deltaPct = baseVal !== 0 ? ((currentVal - baseVal) / baseVal) * 100 : 0;
            const isCurveActive = activeCurveVar === varName;

            return (
              <div
                key={varName}
                style={{
                  padding: "12px",
                  borderRadius: "8px",
                  backgroundColor: isCurveActive ? "#1e293b" : "#172554",
                  border: isCurveActive ? "1px solid #38bdf8" : "1px solid transparent",
                  display: "flex",
                  flexDirection: "column",
                  gap: "6px",
                  cursor: "pointer",
                }}
                onClick={() => setActiveCurveVar(varName)}
              >
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem" }}>
                  <span style={{ fontWeight: 600, color: isCurveActive ? "#38bdf8" : "#f1f5f9" }}>
                    {varName}{" "}
                    <span style={{ fontSize: "0.75rem", color: "#64748b", fontWeight: 400 }}>
                      ({range.unit})
                    </span>
                  </span>
                  <span style={{ fontWeight: 700, color: "#f8fafc" }}>
                    {currentVal.toLocaleString()}{" "}
                    <span
                      style={{
                        fontSize: "0.75rem",
                        color: deltaPct > 0 ? "#4ade80" : deltaPct < 0 ? "#f87171" : "#94a3b8",
                      }}
                    >
                      ({deltaPct >= 0 ? `+${deltaPct.toFixed(1)}%` : `${deltaPct.toFixed(1)}%`})
                    </span>
                  </span>
                </div>

                <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginBottom: "4px" }}>
                  {activePreset.descriptions[varName]}
                </div>

                <input
                  type="range"
                  min={range.min}
                  max={range.max}
                  step={range.step}
                  value={currentVal}
                  onChange={(e) => handleInputChange(varName, parseFloat(e.target.value))}
                  onMouseUp={() => fetchSimulation(inputs)}
                  onTouchEnd={() => fetchSimulation(inputs)}
                  style={{
                    width: "100%",
                    accentColor: "#38bdf8",
                    cursor: "pointer",
                  }}
                />
              </div>
            );
          })}

          {/* Stress-Test Presets Bar */}
          {activePreset.stressPresets.length > 0 && (
            <div style={{ marginTop: "8px" }}>
              <div style={{ fontSize: "0.8rem", color: "#94a3b8", marginBottom: "8px", fontWeight: 600 }}>
                Regulatory Stress Scenarios:
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                {activePreset.stressPresets.map((preset) => {
                  const isSelected = activePresetName === preset.name;
                  return (
                    <button
                      key={preset.name}
                      onClick={() => handleApplyPreset(preset)}
                      style={{
                        padding: "6px 12px",
                        borderRadius: "6px",
                        backgroundColor: isSelected ? "#0284c7" : "#1e293b",
                        color: isSelected ? "#ffffff" : "#94a3b8",
                        border: isSelected ? "1px solid #38bdf8" : "1px solid #334155",
                        fontSize: "0.75rem",
                        fontWeight: 600,
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                      }}
                      title={preset.description}
                    >
                      {preset.name}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Real-time Output & Sensitivity Graph */}
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {/* Status Badge Card */}
          <div
            style={{
              padding: "16px",
              borderRadius: "10px",
              backgroundColor:
                currentStatus === "COMPLIANT"
                  ? "rgba(34, 197, 94, 0.1)"
                  : currentStatus === "WARNING"
                  ? "rgba(234, 179, 8, 0.1)"
                  : "rgba(239, 68, 68, 0.15)",
              border: `1px solid ${
                currentStatus === "COMPLIANT"
                  ? "#22c55e"
                  : currentStatus === "WARNING"
                  ? "#eab308"
                  : "#ef4444"
              }`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div>
              <div style={{ fontSize: "0.8rem", color: "#94a3b8", textTransform: "uppercase" }}>
                Simulated Output
              </div>
              <div style={{ fontSize: "1.8rem", fontWeight: 800, color: "#f8fafc" }}>
                {selectedFormulaId === "crar" || selectedFormulaId === "leverage-ratio"
                  ? `${(localComputedValue * 100).toFixed(2)}%`
                  : localComputedValue.toFixed(4)}{" "}
                <span style={{ fontSize: "0.85rem", color: "#94a3b8", fontWeight: 400 }}>
                  {activePreset.unit}
                </span>
              </div>
            </div>

            <div
              style={{
                padding: "8px 16px",
                borderRadius: "999px",
                fontWeight: 800,
                fontSize: "0.85rem",
                letterSpacing: "0.05em",
                backgroundColor:
                  currentStatus === "COMPLIANT"
                    ? "#15803d"
                    : currentStatus === "WARNING"
                    ? "#a16207"
                    : "#b91c1c",
                color: "#ffffff",
              }}
            >
              {currentStatus}
            </div>
          </div>

          {/* Sensitivity Curve (SVG Graph) */}
          <div
            style={{
              padding: "16px",
              borderRadius: "10px",
              backgroundColor: "#1e293b",
              border: "1px solid #334155",
              display: "flex",
              flexDirection: "column",
              gap: "8px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#cbd5e1" }}>
                Sensitivity Curve: <span style={{ color: "#38bdf8" }}>{activeCurveVar}</span>
              </div>
              <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
                {isSimulating ? "Recalculating..." : "Range: ±25% sweep"}
              </div>
            </div>

            {/* SVG Plot */}
            <div style={{ width: "100%", height: "180px", position: "relative" }}>
              <svg width="100%" height="180" viewBox="0 0 460 180" preserveAspectRatio="none">
                {/* Grid line */}
                <line x1="20" y1="160" x2="450" y2="160" stroke="#334155" strokeWidth="1" />
                <line x1="30" y1="20" x2="30" y2="160" stroke="#334155" strokeWidth="1" />

                {/* Statutory Threshold Reference Line */}
                <line
                  x1="30"
                  y1={thresholdY}
                  x2="450"
                  y2={thresholdY}
                  stroke="#ef4444"
                  strokeWidth="1.5"
                  strokeDasharray="4 4"
                />

                {/* Sensitivity Curve Line */}
                <path d={svgPathData} fill="none" stroke="#38bdf8" strokeWidth="2.5" />
              </svg>

              {/* Threshold label */}
              <div
                style={{
                  position: "absolute",
                  right: "8px",
                  top: `${Math.max(10, Math.min(160, thresholdY - 14))}px`,
                  fontSize: "0.65rem",
                  color: "#ef4444",
                  fontWeight: 600,
                }}
              >
                Threshold ({activePreset.thresholdVal})
              </div>
            </div>
          </div>

          {/* Elasticity Ranking Table */}
          {backendData && backendData.sensitivities.length > 0 && (
            <div
              style={{
                padding: "14px",
                borderRadius: "10px",
                backgroundColor: "#1e293b",
                border: "1px solid #334155",
              }}
            >
              <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#cbd5e1", marginBottom: "8px" }}>
                Sensitivity Elasticity Rankings:
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                {backendData.sensitivities.map((s) => (
                  <div
                    key={s.variable}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      fontSize: "0.8rem",
                      padding: "4px 8px",
                      borderRadius: "4px",
                      backgroundColor: s.variable === activeCurveVar ? "#334155" : "transparent",
                    }}
                  >
                    <span style={{ fontWeight: 600, color: "#f8fafc" }}>
                      #{s.impact_rank} {s.variable}
                    </span>
                    <span style={{ color: "#94a3b8" }}>
                      Elasticity:{" "}
                      <strong style={{ color: s.elasticity > 0 ? "#4ade80" : "#f87171" }}>
                        {s.elasticity > 0 ? `+${s.elasticity}` : s.elasticity}
                      </strong>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SensitivitySimulator;
