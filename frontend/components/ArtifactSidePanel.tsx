"use client";

import { useMemo, useState } from "react";

import { CodeFile, GraphEntity, GraphRelation, ProjectGraphResult } from "../lib/api";

type ArtifactKind = "report" | "code" | "graph";

type ArtifactSidePanelProps = {
  open: boolean;
  collapsed: boolean;
  kind: ArtifactKind;
  reportContent: string;
  reportError: string;
  files: CodeFile[];
  activePath: string;
  codeError: string;
  graph: ProjectGraphResult | null;
  graphError: string;
  artifactUrl: string;
  onOpen: () => void;
  onClose: () => void;
  onToggleCollapse: () => void;
  onSelectKind: (kind: ArtifactKind) => void;
  onSelectFile: (path: string) => void;
};

export function ArtifactSidePanel({
  open,
  collapsed,
  kind,
  reportContent,
  reportError,
  files,
  activePath,
  codeError,
  graph,
  graphError,
  artifactUrl,
  onClose,
  onToggleCollapse,
  onSelectKind,
  onSelectFile,
}: ArtifactSidePanelProps) {
  const activeFile = files.find((file) => file.path === activePath) ?? files[0];
  const [entityType, setEntityType] = useState("");
  const [relationType, setRelationType] = useState("");
  const [query, setQuery] = useState("");
  const [selectedEntityId, setSelectedEntityId] = useState("");

  const graphEntities = graph?.entities ?? [];
  const graphRelations = graph?.relations ?? [];
  const entityTypes = useMemo(() => uniqueValues(graphEntities.map((entity) => entity.entity_type)), [graphEntities]);
  const relationTypes = useMemo(
    () => uniqueValues(graphRelations.map((relation) => relation.relation_type)),
    [graphRelations],
  );
  const filteredEntities = useMemo(
    () =>
      graphEntities.filter((entity) => {
        const text = `${entity.name} ${entity.description ?? ""} ${entity.entity_type}`.toLowerCase();
        return (!entityType || entity.entity_type === entityType) && (!query || text.includes(query.toLowerCase()));
      }),
    [entityType, graphEntities, query],
  );
  const selectedEntity = graphEntities.find((entity) => entity.entity_id === selectedEntityId) ?? filteredEntities[0];
  const visibleRelations = useMemo(
    () =>
      graphRelations.filter((relation) => {
        const touchesSelected =
          !selectedEntity ||
          relation.source_entity_id === selectedEntity.entity_id ||
          relation.target_entity_id === selectedEntity.entity_id;
        return touchesSelected && (!relationType || relation.relation_type === relationType);
      }),
    [graphRelations, relationType, selectedEntity],
  );

  const panelTitle =
    kind === "report"
      ? "研究报告"
      : kind === "graph"
        ? "知识图谱"
        : activeFile?.path ?? "生成代码";
  const panelMeta =
    kind === "report"
      ? "Markdown"
      : kind === "graph"
        ? `${graphEntities.length} entities · ${graphRelations.length} relations`
        : "Code Artifact";

  if (!open) {
    return null;
  }

  if (collapsed) {
    return (
      <aside className="artifact-rail">
        <button type="button" onClick={onToggleCollapse}>
          展开
        </button>
        <button type="button" onClick={onClose}>
          关闭
        </button>
      </aside>
    );
  }

  return (
    <aside className="artifact-side-panel">
      <header className="artifact-panel-header">
        <div>
          <strong>{panelTitle}</strong>
          <span>{panelMeta}</span>
        </div>
        <div className="artifact-panel-actions">
          <button type="button" onClick={onToggleCollapse}>
            最小化
          </button>
          <button type="button" onClick={onClose}>
            关闭
          </button>
        </div>
      </header>

      <div className="artifact-tabs">
        <button className={kind === "report" ? "active" : ""} type="button" onClick={() => onSelectKind("report")}>
          报告
        </button>
        <button className={kind === "code" ? "active" : ""} type="button" onClick={() => onSelectKind("code")}>
          代码
        </button>
        <button className={kind === "graph" ? "active" : ""} type="button" onClick={() => onSelectKind("graph")}>
          图谱
        </button>
        {files.length ? <a href={artifactUrl}>下载 zip</a> : null}
      </div>

      {kind === "report" ? (
        <div className="artifact-content">
          {reportContent ? (
            <pre className="markdown-preview side-preview">{reportContent}</pre>
          ) : (
            <p className="muted">{reportError || "报告还在生成中。"}</p>
          )}
        </div>
      ) : kind === "code" ? (
        <div className="artifact-code-view">
          <div className="side-file-list">
            {files.map((file) => (
              <button
                className={file.path === activeFile?.path ? "active" : ""}
                key={file.path}
                type="button"
                onClick={() => onSelectFile(file.path)}
              >
                {file.path}
              </button>
            ))}
          </div>
          <div className="artifact-content code-content">
            {activeFile ? (
              <pre className="code-preview side-preview">{activeFile.content}</pre>
            ) : (
              <p className="muted">{codeError || "代码文件还在生成中。"}</p>
            )}
          </div>
        </div>
      ) : (
        <GraphBrowser
          entities={filteredEntities}
          relations={visibleRelations}
          allRelations={graphRelations}
          entityTypes={entityTypes}
          relationTypes={relationTypes}
          entityType={entityType}
          relationType={relationType}
          query={query}
          selectedEntity={selectedEntity}
          error={graphError}
          onEntityTypeChange={setEntityType}
          onRelationTypeChange={setRelationType}
          onQueryChange={setQuery}
          onSelectEntity={setSelectedEntityId}
        />
      )}
    </aside>
  );
}

function GraphBrowser({
  entities,
  relations,
  allRelations,
  entityTypes,
  relationTypes,
  entityType,
  relationType,
  query,
  selectedEntity,
  error,
  onEntityTypeChange,
  onRelationTypeChange,
  onQueryChange,
  onSelectEntity,
}: {
  entities: GraphEntity[];
  relations: GraphRelation[];
  allRelations: GraphRelation[];
  entityTypes: string[];
  relationTypes: string[];
  entityType: string;
  relationType: string;
  query: string;
  selectedEntity?: GraphEntity;
  error: string;
  onEntityTypeChange: (value: string) => void;
  onRelationTypeChange: (value: string) => void;
  onQueryChange: (value: string) => void;
  onSelectEntity: (value: string) => void;
}) {
  if (!entities.length && !allRelations.length) {
    return (
      <div className="artifact-content graph-empty">
        <strong>暂无图谱数据</strong>
        <p>{error || "知识图谱会在论文分析完成后生成。"}</p>
      </div>
    );
  }

  return (
    <div className="graph-browser">
      <div className="graph-toolbar">
        <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="搜索实体" />
        <select value={entityType} onChange={(event) => onEntityTypeChange(event.target.value)}>
          <option value="">全部实体</option>
          {entityTypes.map((type) => (
            <option value={type} key={type}>
              {type}
            </option>
          ))}
        </select>
        <select value={relationType} onChange={(event) => onRelationTypeChange(event.target.value)}>
          <option value="">全部关系</option>
          {relationTypes.map((type) => (
            <option value={type} key={type}>
              {type}
            </option>
          ))}
        </select>
      </div>

      <div className="graph-layout">
        <div className="graph-entity-list">
          {entities.map((entity) => (
            <button
              className={entity.entity_id === selectedEntity?.entity_id ? "active" : ""}
              type="button"
              key={entity.entity_id}
              onClick={() => onSelectEntity(entity.entity_id)}
            >
              <span>{entity.entity_type}</span>
              <strong>{entity.name}</strong>
              {entity.description ? <small>{entity.description}</small> : null}
            </button>
          ))}
        </div>

        <div className="graph-detail">
          {selectedEntity ? (
            <section className="graph-card">
              <div className="graph-card-head">
                <span>{selectedEntity.entity_type}</span>
                <strong>{selectedEntity.name}</strong>
              </div>
              {selectedEntity.description ? <p>{selectedEntity.description}</p> : null}
              <EvidenceTags chunkIds={selectedEntity.source_chunk_ids} />
            </section>
          ) : null}

          <section className="graph-card graph-relations">
            <div className="graph-card-head">
              <span>relations</span>
              <strong>一跳邻域</strong>
            </div>
            {relations.length ? (
              relations.map((relation) => (
                <article key={relation.relation_id}>
                  <div>
                    <strong>{relation.source_name || relation.source_entity_id}</strong>
                    <span>{relation.relation_type}</span>
                    <strong>{relation.target_name || relation.target_entity_id}</strong>
                  </div>
                  {relation.description ? <p>{relation.description}</p> : null}
                  <EvidenceTags chunkIds={relation.source_chunk_ids} />
                </article>
              ))
            ) : (
              <p className="muted">当前筛选下没有关系。</p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function EvidenceTags({ chunkIds }: { chunkIds: string[] }) {
  if (!chunkIds.length) {
    return null;
  }
  return (
    <div className="graph-evidence">
      {chunkIds.slice(0, 6).map((chunkId) => (
        <span key={chunkId}>{chunkId}</span>
      ))}
    </div>
  );
}

function uniqueValues(values: string[]) {
  return Array.from(new Set(values.filter(Boolean))).sort();
}
