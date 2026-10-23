export interface KnowledgeNode {
  id: string;
  parent_id: string | null;
  content: string;
  depth: number;
  created_at: string;
  model_used?: string;
  children?: KnowledgeNode[];
}