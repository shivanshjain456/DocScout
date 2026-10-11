import React, { useEffect, useState } from "react";

export interface GraphNode {
  id: string;
  label: string;
  domain: string;
  level: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
}

export interface SubgraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  root_id: string;
}

export interface ConceptGraphViewProps {
  docId: string;
  apiKey?: string;
  maxNodes?: number;
  depth?: number;
  onSelectNode?: (nodeId: string) => void;
}

export const ConceptGraphView: React.FC<ConceptGraphViewProps> = ({
  docId,
  apiKey,
  maxNodes = 25,
  depth = 2,
  onSelectNode,
}) => {
  const [data, setData] = useState<SubgraphResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const headers: Record<string, string> = {};
    if (apiKey) {
      headers["X-API-Key"] = apiKey;
    }

    fetch(`/v1/graph/subgraph/${encodeURIComponent(docId)}?depth=${depth}&max_nodes=${maxNodes}`, {
      headers,
    })
      .then(async (res) => {
        if (!res.ok) {
          if (res.status === 404) {
            throw new Error("No concept relationships mapped for this document");
          }
          throw new Error(`Failed to load concept graph (HTTP ${res.status})`);
        }
        return res.json() as Promise<SubgraphResponse>;
      })
      .then((json) => {
        if (active) {
          setData(json);
          setLoading(false);
        }
      })
      .catch((err: Error) => {
        if (active) {
          setError(err.message);
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [docId, apiKey, maxNodes, depth]);

  if (loading) {
    return (
      <div className="concept-graph-loading" style={{ padding: "16px", color: "var(--color-text-muted, #64748b)" }}>
        Loading concept graph projection...
      </div>
    );
  }

  if (error || !data || data.nodes.length === 0) {
    return (
      <div
        className="concept-graph-fallback"
        role="alert"
        style={{
          padding: "16px",
          borderRadius: "6px",
          background: "var(--color-bg-subtle, #f8fafc)",
          border: "1px solid var(--color-border, #e2e8f0)",
          color: "var(--color-text-secondary, #475569)",
        }}
      >
        {error || "No concept relationships mapped for this document"}
      </div>
    );
  }

  // Radial / circular positioning layout for SVG rendering
  const width = 640;
  const height = 400;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(centerX, centerY) - 60;

  const nodePositions = new Map<string, { x: number; y: number }>();
  const rootNode = data.nodes.find((n) => n.id === data.root_id) || data.nodes[0];
  nodePositions.set(rootNode.id, { x: centerX, y: centerY });

  const otherNodes = data.nodes.filter((n) => n.id !== rootNode.id);
  const angleStep = otherNodes.length > 0 ? (2 * Math.PI) / otherNodes.length : 0;

  otherNodes.forEach((node, idx) => {
    const angle = idx * angleStep;
    nodePositions.set(node.id, {
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle),
    });
  });

  const handleNodeClick = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    if (onSelectNode) {
      onSelectNode(nodeId);
    }
  };

  return (
    <div
      className="concept-graph-container"
      style={{
        border: "1px solid var(--color-border, #e2e8f0)",
        borderRadius: "8px",
        overflow: "hidden",
        background: "var(--color-bg, #ffffff)",
      }}
    >
      <div
        style={{
          padding: "8px 16px",
          background: "var(--color-bg-subtle, #f8fafc)",
          borderBottom: "1px solid var(--color-border, #e2e8f0)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: "13px",
        }}
      >
        <span style={{ fontWeight: 600 }}>2-Hop Concept Subgraph</span>
        <span style={{ color: "#64748b" }}>
          {data.nodes.length} nodes · {data.edges.length} relations
        </span>
      </div>

      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: "block", width: "100%", height: "auto" }}>
        <defs>
          <marker
            id="graph-arrow"
            viewBox="0 -5 10 10"
            refX={20}
            refY={0}
            markerWidth={6}
            markerHeight={6}
            orient="auto"
          >
            <path d="M0,-5L10,0L0,5" fill="#94a3b8" />
          </marker>
        </defs>

        {/* Edges */}
        {data.edges.map((edge, idx) => {
          const srcPos = nodePositions.get(edge.source);
          const tgtPos = nodePositions.get(edge.target);
          if (!srcPos || !tgtPos) return null;

          return (
            <g key={`edge-${idx}`}>
              <line
                x1={srcPos.x}
                y1={srcPos.y}
                x2={tgtPos.x}
                y2={tgtPos.y}
                stroke="#cbd5e1"
                strokeWidth={1.5}
                markerEnd="url(#graph-arrow)"
              />
              <text
                x={(srcPos.x + tgtPos.x) / 2}
                y={(srcPos.y + tgtPos.y) / 2 - 4}
                textAnchor="middle"
                fontSize={9}
                fill="#64748b"
              >
                {edge.relation}
              </text>
            </g>
          );
        })}

        {/* Nodes */}
        {data.nodes.map((node) => {
          const pos = nodePositions.get(node.id);
          if (!pos) return null;
          const isRoot = node.id === data.root_id;
          const isSelected = node.id === selectedNodeId;

          return (
            <g
              key={node.id}
              onClick={() => handleNodeClick(node.id)}
              style={{ cursor: "pointer" }}
            >
              <circle
                cx={pos.x}
                cy={pos.y}
                r={isRoot ? 18 : 14}
                fill={isRoot ? "#2563eb" : isSelected ? "#0284c7" : "#0ea5e9"}
                stroke={isSelected ? "#0f172a" : "#ffffff"}
                strokeWidth={2}
              />
              <text
                x={pos.x}
                y={pos.y + (isRoot ? 30 : 24)}
                textAnchor="middle"
                fontSize={11}
                fontWeight={isRoot ? 600 : 400}
                fill="#1e293b"
              >
                {node.label.length > 20 ? `${node.label.slice(0, 18)}…` : node.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};

export default ConceptGraphView;
