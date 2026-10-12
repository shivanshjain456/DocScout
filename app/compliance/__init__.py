"""Compliance and Quantitative Verification module (Pillar 3)."""

from __future__ import annotations

from app.compliance.boundary_validator import (
    StatutoryBoundaryValidator,
    get_default_boundary_validator,
)
from app.compliance.consistency_auditor import (
    AnomalyType,
    AuditResult,
    AuditSeverity,
    AuditSubmission,
    AuditTable,
    ConsistencyAnomaly,
    MathematicalSanityAuditor,
    get_default_consistency_auditor,
)
from app.compliance.dependency_graph import (
    CircularDependencyError,
    DependencyEdge,
    DependencyGraphBuilder,
    DependencyNode,
    FormulaDependencyGraph,
    NodeType,
    get_graph,
    list_registered_graphs,
    register_graph,
)
from app.compliance.formula_engine import FormulaEngine, get_default_formula_engine
from app.compliance.simulator import ComplianceSimulator, get_default_compliance_simulator
from app.compliance.standards_registry import (
    StandardDefinition,
    StandardsRegistry,
    get_default_standards_registry,
)
from app.compliance.unit_normalizer import (
    IndianFinancialUnitNormalizer,
    NormalizedFinancialValue,
    format_indian_number,
    format_international_number,
    get_default_unit_normalizer,
)
from app.ingest.standard_linker import (
    AnnotatedFormula,
    StandardFormulaAnnotator,
    StandardLinkerConfig,
    get_default_standard_annotator,
)

__all__ = [
    "AnnotatedFormula",
    "AnomalyType",
    "AuditResult",
    "AuditSeverity",
    "AuditSubmission",
    "AuditTable",
    "CircularDependencyError",
    "ComplianceSimulator",
    "ConsistencyAnomaly",
    "DependencyEdge",
    "DependencyGraphBuilder",
    "DependencyNode",
    "FormulaDependencyGraph",
    "FormulaEngine",
    "IndianFinancialUnitNormalizer",
    "MathematicalSanityAuditor",
    "NodeType",
    "NormalizedFinancialValue",
    "StandardDefinition",
    "StandardFormulaAnnotator",
    "StandardLinkerConfig",
    "StandardsRegistry",
    "StatutoryBoundaryValidator",
    "format_indian_number",
    "format_international_number",
    "get_default_boundary_validator",
    "get_default_compliance_simulator",
    "get_default_consistency_auditor",
    "get_default_formula_engine",
    "get_default_standard_annotator",
    "get_default_standards_registry",
    "get_default_unit_normalizer",
    "get_graph",
    "list_registered_graphs",
    "register_graph",
]
