"""Formula Dependency Graph Builder (FEAT-029).

Constructs directed acyclic graphs (DAGs) of statutory formula variables and intermediate
metrics to determine valid topological calculation orders, detect circular dependencies,
and identify missing prerequisite data points across multi-step regulatory returns.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog

from app.compliance.formula_engine import (
    FormulaEngine,
    SafeMathEvaluator,
)

logger = structlog.get_logger("docscout.compliance.dependency_graph")


class NodeType(StrEnum):
    """Categorization of graph nodes in the calculation DAG."""

    INPUT = "INPUT"  # Exogenous input supplied by reporting entity
    INTERMEDIATE = "INTERMEDIATE"  # Computed value serving as prerequisite for downstream formulas
    OUTPUT = "OUTPUT"  # Terminal regulatory return or ratio


@dataclass
class DependencyNode:
    """Node representing a quantitative parameter, ratio, or intermediate variable."""

    node_id: str
    name: str
    node_type: NodeType
    expression: str | None = None
    description: str = ""
    category: str = "general"
    unit: str = "ratio"
    tier: int = 0
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "node_type": self.node_type.value,
            "expression": self.expression,
            "description": self.description,
            "category": self.category,
            "unit": self.unit,
            "tier": self.tier,
            "dependencies": self.dependencies,
        }


@dataclass
class DependencyEdge:
    """Directed dependency link between an antecedent and a dependent variable."""

    source: str
    target: str
    parameter_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "parameter_name": self.parameter_name or self.source,
        }


class CircularDependencyError(ValueError):
    """Raised when circular or recursive dependencies are detected in the formula graph."""

    def __init__(self, cycle_path: list[str]) -> None:
        self.cycle_path = cycle_path
        super().__init__(
            f"Circular dependency detected in calculation graph: {' -> '.join(cycle_path)}"
        )


@dataclass
class FormulaDependencyGraph:
    """Directed acyclic graph of statutory variables and computational stages."""

    graph_id: str
    name: str
    domain: str
    description: str
    nodes: dict[str, DependencyNode] = field(default_factory=dict)
    edges: list[DependencyEdge] = field(default_factory=list)
    topological_order: list[str] = field(default_factory=list)
    execution_tiers: list[list[str]] = field(default_factory=list)
    target_variables: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "name": self.name,
            "domain": self.domain,
            "description": self.description,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "topological_order": self.topological_order,
            "execution_tiers": self.execution_tiers,
            "target_variables": self.target_variables,
        }

    def compute_topological_sort(self) -> list[str]:
        """Compute valid topological ordering using Kahn's algorithm with cycle detection."""
        in_degree: dict[str, int] = {node_id: 0 for node_id in self.nodes}
        adj: dict[str, list[str]] = {node_id: [] for node_id in self.nodes}

        for edge in self.edges:
            if edge.source in adj and edge.target in in_degree:
                adj[edge.source].append(edge.target)
                in_degree[edge.target] += 1

        queue = [node_id for node_id, deg in in_degree.items() if deg == 0]
        order: list[str] = []

        while queue:
            curr = queue.pop(0)
            order.append(curr)

            for neighbor in adj[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) < len(self.nodes):
            # Circular dependency exists. Find cycle path.
            cycle = self._detect_cycle()
            raise CircularDependencyError(cycle)

        self.topological_order = order
        self._compute_tiers(order, adj)
        return order

    def _compute_tiers(self, order: list[str], adj: dict[str, list[str]]) -> None:
        """Assign topological execution tiers to enable parallel calculation stages."""
        tier_map: dict[str, int] = {}
        for node_id in order:
            node = self.nodes[node_id]
            if not node.dependencies:
                tier_map[node_id] = 0
            else:
                max_parent_tier = max(tier_map.get(dep, 0) for dep in node.dependencies)
                tier_map[node_id] = max_parent_tier + 1
            node.tier = tier_map[node_id]

        max_tier = max(tier_map.values()) if tier_map else 0
        tiers: list[list[str]] = [[] for _ in range(max_tier + 1)]
        for node_id in order:
            t = tier_map[node_id]
            tiers[t].append(node_id)

        self.execution_tiers = [t for t in tiers if t]

    def _detect_cycle(self) -> list[str]:
        """Trace the exact cycle path using Depth First Search."""
        visited: dict[str, int] = {}  # 0: unvisited, 1: visiting, 2: visited
        adj: dict[str, list[str]] = {node_id: [] for node_id in self.nodes}
        for e in self.edges:
            if e.source in adj and e.target in self.nodes:
                adj[e.source].append(e.target)

        def dfs(node: str, stack: list[str]) -> list[str] | None:
            visited[node] = 1
            stack.append(node)

            for nxt in adj.get(node, []):
                if visited.get(nxt, 0) == 1:
                    idx = stack.index(nxt)
                    return stack[idx:] + [nxt]
                if visited.get(nxt, 0) == 0:
                    res = dfs(nxt, stack)
                    if res is not None:
                        return res

            visited[node] = 2
            stack.pop()
            return None

        for n in self.nodes:
            if visited.get(n, 0) == 0:
                cycle_found = dfs(n, [])
                if cycle_found:
                    return cycle_found

        return ["unknown_cycle"]

    def get_prerequisites(self, target: str) -> set[str]:
        """Recursively gather all direct and transitive prerequisite variables for a target."""
        prereqs: set[str] = set()
        visited: set[str] = set()

        def collect(curr: str) -> None:
            if curr in visited or curr not in self.nodes:
                return
            visited.add(curr)
            node = self.nodes[curr]
            for dep in node.dependencies:
                prereqs.add(dep)
                collect(dep)

        collect(target)
        return prereqs

    def check_prerequisites(
        self,
        target_variables: list[str],
        provided_inputs: dict[str, float],
    ) -> dict[str, Any]:
        """Check whether sufficient inputs are available to compute requested target metrics."""
        targets = target_variables or self.target_variables
        all_required_inputs: set[str] = set()

        for t in targets:
            if t in self.nodes:
                prereqs = self.get_prerequisites(t)
                for p in prereqs:
                    if self.nodes.get(p) and self.nodes[p].node_type == NodeType.INPUT:
                        all_required_inputs.add(p)
                if self.nodes[t].node_type == NodeType.INPUT:
                    all_required_inputs.add(t)

        provided_keys = {k.lower().strip() for k in provided_inputs.keys()}
        required_keys = {k.lower().strip() for k in all_required_inputs}

        missing = sorted(required_keys - provided_keys)
        provided = sorted(required_keys & provided_keys)

        total_needed = len(required_keys)
        pct = (len(provided) / total_needed * 100.0) if total_needed > 0 else 100.0

        # Determine which intermediate nodes can be resolved with current inputs
        resolvable: list[str] = []
        known_values = set(provided_keys)
        for node_id in self.topological_order:
            node = self.nodes[node_id]
            if node.node_type != NodeType.INPUT:
                if all(dep.lower() in known_values for dep in node.dependencies):
                    resolvable.append(node_id)
                    known_values.add(node_id.lower())

        is_ready = len(missing) == 0

        return {
            "is_ready": is_ready,
            "target_variables": targets,
            "required_inputs_count": total_needed,
            "provided_inputs": provided,
            "missing_inputs": missing,
            "completion_percentage": round(pct, 1),
            "resolvable_intermediates": resolvable,
        }

    def evaluate_cascade(
        self,
        provided_inputs: dict[str, float],
        engine: FormulaEngine | None = None,
        evaluator: SafeMathEvaluator | None = None,
    ) -> dict[str, Any]:
        """Execute calculations in strict topological order and return computed trace."""
        calc_evaluator = evaluator or (
            engine.evaluator if engine and hasattr(engine, "evaluator") else SafeMathEvaluator()
        )
        values: dict[str, float] = {k.lower().strip(): float(v) for k, v in provided_inputs.items()}
        trace: list[dict[str, Any]] = []
        missing_errors: list[str] = []

        if not self.topological_order:
            self.compute_topological_sort()

        for node_id in self.topological_order:
            node = self.nodes[node_id]
            if node.node_type == NodeType.INPUT:
                if node_id.lower() in values:
                    trace.append(
                        {
                            "node_id": node_id,
                            "node_type": "INPUT",
                            "value": values[node_id.lower()],
                            "status": "PROVIDED",
                        }
                    )
                else:
                    trace.append(
                        {
                            "node_id": node_id,
                            "node_type": "INPUT",
                            "value": None,
                            "status": "MISSING",
                        }
                    )
                    missing_errors.append(node_id)
                continue

            # Computed node
            if not node.expression:
                continue

            # Verify all dependencies are available
            deps_available = all(dep.lower() in values for dep in node.dependencies)
            if not deps_available:
                missing_for_node = [dep for dep in node.dependencies if dep.lower() not in values]
                trace.append(
                    {
                        "node_id": node_id,
                        "node_type": node.node_type.value,
                        "expression": node.expression,
                        "value": None,
                        "status": "BLOCKED",
                        "missing_prerequisites": missing_for_node,
                    }
                )
                missing_errors.append(node_id)
                continue

            try:
                computed_val = calc_evaluator.evaluate(node.expression, values)
                values[node_id.lower()] = computed_val
                trace.append(
                    {
                        "node_id": node_id,
                        "node_type": node.node_type.value,
                        "expression": node.expression,
                        "value": round(computed_val, 4),
                        "status": "COMPUTED",
                        "tier": node.tier,
                    }
                )
            except Exception as exc:
                trace.append(
                    {
                        "node_id": node_id,
                        "node_type": node.node_type.value,
                        "expression": node.expression,
                        "value": None,
                        "status": "ERROR",
                        "error": str(exc),
                    }
                )
                missing_errors.append(node_id)

        target_outputs = {
            t: values.get(t.lower()) for t in self.target_variables if t.lower() in values
        }

        return {
            "is_complete": len(missing_errors) == 0,
            "target_outputs": target_outputs,
            "computed_values": values,
            "trace": trace,
            "missing_variables": sorted(set(missing_errors)),
        }


def extract_variables_from_expression(expression: str) -> list[str]:
    """Parse mathematical expression into its free variable identifiers using AST."""
    clean_expr = (
        expression.replace("×", "*")
        .replace("÷", "/")
        .replace("–", "-")
        .replace("\u2014", "-")
        .replace("^", "**")
    )
    clean_expr = re.sub(r"(?<=\d|\))\s*[xX]\s*(?=\d|\()", " * ", clean_expr)

    try:
        tree = ast.parse(clean_expr, mode="eval")
    except SyntaxError:
        # Fallback to regex word tokens
        words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", clean_expr)
        return sorted({w for w in words if w.lower() not in ("sum", "max", "min", "abs", "round")})

    vars_found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id.lower() not in ("sum", "max", "min", "abs", "round", "math"):
                vars_found.add(node.id)

    return sorted(vars_found)


class DependencyGraphBuilder:
    """Factory and registry for regulatory formula dependency graphs."""

    @classmethod
    def build_from_formulas(
        cls,
        formulas: list[dict[str, Any]],
        graph_id: str,
        name: str,
        domain: str = "custom",
        description: str = "",
        target_variables: list[str] | None = None,
    ) -> FormulaDependencyGraph:
        """Construct a FormulaDependencyGraph from a list of formula definitions."""
        nodes: dict[str, DependencyNode] = {}
        edges: list[DependencyEdge] = []
        formula_targets: set[str] = set()

        # Phase 1: Register all formula outputs
        for f in formulas:
            target_id = f.get("id") or f.get("target") or f.get("name")
            if not target_id:
                continue
            expr = f.get("expression") or f.get("formula") or ""
            desc = f.get("description") or ""
            cat = f.get("category") or "custom"
            unit = f.get("unit") or "ratio"
            deps = f.get("dependencies") or extract_variables_from_expression(expr)

            formula_targets.add(target_id)
            nodes[target_id] = DependencyNode(
                node_id=target_id,
                name=f.get("name") or target_id,
                node_type=NodeType.OUTPUT
                if (target_variables and target_id in target_variables)
                else NodeType.INTERMEDIATE,
                expression=expr,
                description=desc,
                category=cat,
                unit=unit,
                dependencies=deps,
            )

        # Phase 2: Register raw input nodes and build edges
        for target_id, node in list(nodes.items()):
            for dep in node.dependencies:
                if dep not in nodes:
                    # Raw input variable
                    nodes[dep] = DependencyNode(
                        node_id=dep,
                        name=dep.replace("_", " ").title(),
                        node_type=NodeType.INPUT,
                        expression=None,
                        description=f"Exogenous input {dep}",
                        category=node.category,
                        dependencies=[],
                    )
                edges.append(DependencyEdge(source=dep, target=target_id))

        targets = target_variables or list(formula_targets)
        # Refine node types
        for t in targets:
            if t in nodes:
                nodes[t].node_type = NodeType.OUTPUT

        graph = FormulaDependencyGraph(
            graph_id=graph_id,
            name=name,
            domain=domain,
            description=description,
            nodes=nodes,
            edges=edges,
            target_variables=targets,
        )

        graph.compute_topological_sort()
        return graph

    @classmethod
    def get_template(cls, template_id: str) -> FormulaDependencyGraph:
        """Retrieve pre-built canonical regulatory calculation graph template."""
        tid = template_id.lower().strip()
        if tid in ("basel3_crar", "crar", "capital_adequacy"):
            return cls._build_basel3_template()
        if tid in ("lcr_framework", "lcr", "liquidity_coverage_ratio"):
            return cls._build_lcr_template()
        if tid in ("asset_quality_irac", "irac", "pcr"):
            return cls._build_irac_template()
        if tid in ("software_carbon_intensity", "sci"):
            return cls._build_sci_template()

        raise KeyError(f"Unknown formula dependency graph template '{template_id}'")

    @classmethod
    def list_templates(cls) -> list[dict[str, Any]]:
        """List metadata for all built-in regulatory calculation graph templates."""
        return [
            {
                "template_id": "basel3_crar",
                "name": "Basel III Capital Adequacy Ratio (CRAR) Multi-Stage DAG",
                "domain": "banking",
                "stages_count": 11,
                "target_variables": ["crar", "tier1_ratio", "cet1_ratio"],
                "description": "Multi-tier regulatory capital computation from raw equity components to final CRAR.",
            },
            {
                "template_id": "lcr_framework",
                "name": "Liquidity Coverage Ratio (LCR) 30-Day Stress DAG",
                "domain": "liquidity",
                "stages_count": 6,
                "target_variables": ["lcr"],
                "description": "High Quality Liquid Assets (HQLA) after haircuts over 30-day net stressed cash outflows.",
            },
            {
                "template_id": "asset_quality_irac",
                "name": "Prudential Asset Quality & Provision Coverage DAG",
                "domain": "credit_risk",
                "stages_count": 6,
                "target_variables": ["pcr", "nnpa_ratio", "gnpa_ratio"],
                "description": "Asset classification breakdown (Substandard, Doubtful, Loss) into GNPA, NNPA, and PCR.",
            },
            {
                "template_id": "software_carbon_intensity",
                "name": "ISO/IEC 21031 Software Carbon Intensity (SCI) DAG",
                "domain": "climate",
                "stages_count": 4,
                "target_variables": ["sci"],
                "description": "Operational energy and embodied carbon divided by functional unit of scale.",
            },
        ]

    @classmethod
    def _build_basel3_template(cls) -> FormulaDependencyGraph:
        formulas = [
            {
                "id": "cet1_capital",
                "name": "Common Equity Tier 1 (CET1)",
                "expression": "common_shares + retained_earnings + statutory_reserves - regulatory_deductions",
                "category": "capital",
                "unit": "INR",
            },
            {
                "id": "tier1_capital",
                "name": "Tier 1 Capital",
                "expression": "cet1_capital + additional_tier1",
                "category": "capital",
                "unit": "INR",
            },
            {
                "id": "tier2_capital",
                "name": "Tier 2 Capital",
                "expression": "subordinated_debt + general_provisions",
                "category": "capital",
                "unit": "INR",
            },
            {
                "id": "total_capital",
                "name": "Total Regulatory Capital",
                "expression": "tier1_capital + tier2_capital",
                "category": "capital",
                "unit": "INR",
            },
            {
                "id": "total_rwa",
                "name": "Total Risk-Weighted Assets (RWA)",
                "expression": "credit_rwa + market_rwa + operational_rwa",
                "category": "rwa",
                "unit": "INR",
            },
            {
                "id": "crar",
                "name": "Capital to Risk-Weighted Assets Ratio (CRAR)",
                "expression": "(total_capital / total_rwa) * 100",
                "category": "ratio",
                "unit": "%",
            },
            {
                "id": "tier1_ratio",
                "name": "Tier 1 Capital Ratio",
                "expression": "(tier1_capital / total_rwa) * 100",
                "category": "ratio",
                "unit": "%",
            },
            {
                "id": "cet1_ratio",
                "name": "Common Equity Tier 1 Ratio",
                "expression": "(cet1_capital / total_rwa) * 100",
                "category": "ratio",
                "unit": "%",
            },
        ]
        return cls.build_from_formulas(
            formulas=formulas,
            graph_id="basel3_crar",
            name="Basel III Capital Adequacy Return",
            domain="banking",
            description="Hierarchical regulatory return DAG computing CET1, Tier 1, Total Capital, RWA, and CRAR.",
            target_variables=["crar", "tier1_ratio", "cet1_ratio"],
        )

    @classmethod
    def _build_lcr_template(cls) -> FormulaDependencyGraph:
        formulas = [
            {
                "id": "level1_assets",
                "name": "Level 1 Liquid Assets",
                "expression": "level1_cash_reserves + level1_gov_bonds",
                "category": "liquidity",
                "unit": "INR",
            },
            {
                "id": "level2a_assets",
                "name": "Level 2A Corporate Bonds",
                "expression": "level2a_corporate_bonds",
                "category": "liquidity",
                "unit": "INR",
            },
            {
                "id": "total_hqla",
                "name": "Total High Quality Liquid Assets (HQLA)",
                "expression": "level1_assets + (level2a_assets * 0.85)",
                "category": "liquidity",
                "unit": "INR",
            },
            {
                "id": "net_cash_outflows",
                "name": "30-Day Net Cash Outflows",
                "expression": "stressed_30d_cash_outflows - min(stressed_30d_cash_inflows, stressed_30d_cash_outflows * 0.75)",
                "category": "liquidity",
                "unit": "INR",
            },
            {
                "id": "lcr",
                "name": "Liquidity Coverage Ratio (LCR)",
                "expression": "(total_hqla / net_cash_outflows) * 100",
                "category": "ratio",
                "unit": "%",
            },
        ]
        return cls.build_from_formulas(
            formulas=formulas,
            graph_id="lcr_framework",
            name="Liquidity Coverage Ratio Framework",
            domain="liquidity",
            description="30-day stressed liquidity calculation factoring regulatory haircuts and inflow caps.",
            target_variables=["lcr"],
        )

    @classmethod
    def _build_irac_template(cls) -> FormulaDependencyGraph:
        formulas = [
            {
                "id": "gross_npa",
                "name": "Gross Non-Performing Assets",
                "expression": "substandard_assets + doubtful_assets + loss_assets",
                "category": "credit_risk",
                "unit": "INR",
            },
            {
                "id": "net_npa",
                "name": "Net Non-Performing Assets",
                "expression": "gross_npa - cumulative_provisions",
                "category": "credit_risk",
                "unit": "INR",
            },
            {
                "id": "pcr",
                "name": "Provision Coverage Ratio (PCR)",
                "expression": "(cumulative_provisions / gross_npa) * 100",
                "category": "ratio",
                "unit": "%",
            },
            {
                "id": "gnpa_ratio",
                "name": "Gross NPA Ratio",
                "expression": "(gross_npa / gross_advances) * 100",
                "category": "ratio",
                "unit": "%",
            },
            {
                "id": "nnpa_ratio",
                "name": "Net NPA Ratio",
                "expression": "(net_npa / net_advances) * 100",
                "category": "ratio",
                "unit": "%",
            },
        ]
        return cls.build_from_formulas(
            formulas=formulas,
            graph_id="asset_quality_irac",
            name="Prudential Asset Quality & Provisioning",
            domain="credit_risk",
            description="IRAC norms multi-step return reconciling GNPA, NNPA, PCR, and NPA percentages.",
            target_variables=["pcr", "nnpa_ratio", "gnpa_ratio"],
        )

    @classmethod
    def _build_sci_template(cls) -> FormulaDependencyGraph:
        formulas = [
            {
                "id": "operational_emissions",
                "name": "Operational Emissions (O)",
                "expression": "energy_consumption_kwh * grid_carbon_intensity",
                "category": "emissions",
                "unit": "gCO2eq",
            },
            {
                "id": "total_emissions",
                "name": "Total Carbon Emissions (C)",
                "expression": "operational_emissions + embodied_carbon",
                "category": "emissions",
                "unit": "gCO2eq",
            },
            {
                "id": "sci",
                "name": "Software Carbon Intensity (SCI)",
                "expression": "total_emissions / functional_unit_r",
                "category": "ratio",
                "unit": "gCO2eq/user",
            },
        ]
        return cls.build_from_formulas(
            formulas=formulas,
            graph_id="software_carbon_intensity",
            name="Software Carbon Intensity (ISO/IEC 21031)",
            domain="climate",
            description="Operational energy and embodied carbon scaled across functional units.",
            target_variables=["sci"],
        )


_IN_MEMORY_GRAPHS: dict[str, FormulaDependencyGraph] = {}


def register_graph(graph: FormulaDependencyGraph) -> None:
    """Register custom formula dependency graph in the runtime cache."""
    _IN_MEMORY_GRAPHS[graph.graph_id] = graph


def get_graph(graph_id: str) -> FormulaDependencyGraph:
    """Retrieve graph instance by ID from registered custom graphs or canonical templates."""
    if graph_id in _IN_MEMORY_GRAPHS:
        return _IN_MEMORY_GRAPHS[graph_id]
    return DependencyGraphBuilder.get_template(graph_id)


def list_registered_graphs() -> list[dict[str, Any]]:
    """List summary information for all active graphs and built-in statutory templates."""
    templates = DependencyGraphBuilder.list_templates()
    customs = [
        {
            "template_id": g.graph_id,
            "name": g.name,
            "domain": g.domain,
            "stages_count": len(g.execution_tiers),
            "target_variables": g.target_variables,
            "description": g.description,
        }
        for g in _IN_MEMORY_GRAPHS.values()
    ]
    return customs + templates
