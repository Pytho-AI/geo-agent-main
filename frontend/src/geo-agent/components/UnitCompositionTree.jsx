import React, { useEffect, useState } from 'react'
import { getSubordinateTree } from '../utils/unitMetadata'

function countAll(nodes) {
  let n = 0
  for (const node of nodes) n += 1 + countAll(node.children)
  return n
}

/**
 * UnitCompositionTree — "Unit composition" section of UnitMetadataPanel.
 *
 * Renders the clicked unit's full subordinate hierarchy (computed client-side
 * from the resolved-OOB snapshot's parent_unit strings, see
 * utils/unitMetadata.js getSubordinateTree) as a collapsible nested list.
 * Direct children are always visible; deeper levels start collapsed.
 * Clicking a unit name drills the panel down into that unit; the ⌖ button
 * (or a right-click on the name, mirroring the map gesture) opens the
 * per-target generation menu for subordinates that exist as map entities.
 *
 * The section is omitted entirely when the unit has no subordinates — most
 * OOB units are leaf companies and an always-on "none" row is noise (unlike
 * equipment, where absence is operationally meaningful).
 *
 * Props:
 *   unit                  fused named_unit record (null for props-only pins
 *                         — sub-positions etc.; those have no kg_id and so
 *                         no subordinates)
 *   onSelectUnit(rec)     drill the panel down into this unit
 *   resolveTargetEntityId(rec) → geo-agent entity id | null — gates the
 *                         generate affordance (units not painted on the map
 *                         can't be targeted)
 *   onGenerate(rec, entityId, event)  open the generation menu
 */
export function UnitCompositionTree({ unit, onSelectUnit, resolveTargetEntityId, onGenerate }) {
  const [tree, setTree] = useState(null)
  const [expanded, setExpanded] = useState(() => new Set())

  useEffect(() => {
    let cancelled = false
    setTree(null)
    setExpanded(new Set())
    getSubordinateTree(unit)
      .then((t) => { if (!cancelled) setTree(t) })
      .catch(() => { if (!cancelled) setTree([]) })
    return () => { cancelled = true }
  }, [unit])

  if (!tree || tree.length === 0) return null

  const toggle = (key) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const renderNodes = (nodes) => (
    <ul className="unit-meta-tree">
      {nodes.map((node) => {
        const hasKids = node.children.length > 0
        const isOpen = expanded.has(node.key)
        const targetId = resolveTargetEntityId ? resolveTargetEntityId(node.unit) : null
        const canGenerate = Boolean(targetId && onGenerate)
        return (
          <li key={node.key}>
            <div className="unit-meta-tree-row">
              {hasKids ? (
                <button
                  className="unit-meta-tree-caret"
                  onClick={() => toggle(node.key)}
                  aria-label={isOpen ? 'Collapse' : 'Expand'}
                >
                  {isOpen ? '▾' : '▸'}
                </button>
              ) : (
                <span className="unit-meta-tree-spacer" />
              )}
              <button
                className="unit-meta-tree-name"
                onClick={() => onSelectUnit(node.unit)}
                onContextMenu={(e) => {
                  if (!canGenerate) return
                  e.preventDefault()
                  onGenerate(node.unit, targetId, e)
                }}
                title={node.unit.name}
              >
                {node.unit.name}
              </button>
              {node.unit.echelon ? (
                <span className="unit-meta-tree-ech">{node.unit.echelon}</span>
              ) : null}
              {canGenerate && (
                <button
                  className="unit-meta-tree-gen"
                  title={`Generate targeting products for ${node.unit.name}`}
                  aria-label={`Generate targeting products for ${node.unit.name}`}
                  onClick={(e) => onGenerate(node.unit, targetId, e)}
                >
                  ⌖
                </button>
              )}
            </div>
            {hasKids && isOpen && renderNodes(node.children)}
          </li>
        )
      })}
    </ul>
  )

  return (
    <div className="unit-meta-section">
      <div className="unit-meta-section-label">Unit composition ({countAll(tree)})</div>
      {renderNodes(tree)}
    </div>
  )
}
