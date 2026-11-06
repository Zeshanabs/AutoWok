export type ResearchProject = {
  id: string;
  workspace_id: string;
  brand_id: string | null;
  created_by: string;
  title: string;
  research_question: string;
  category: string;
  target_audience: string | null;
  geographic_scope: string | null;
  language: string;
  recency_preference: string | null;
  research_depth: string;
  status: string;
  current_stage: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type ResearchReport = {
  id: string;
  research_id: string;
  executive_summary: string | null;
  key_findings: string[];
  trends: string[];
  opportunities: string[];
  risks: string[];
  audience_insights: string[];
  competitor_insights: string[];
  content_angles: string[];
  limitations: string[];
  generated_by_model: string | null;
  created_at: string;
  updated_at: string;
};

export type ResearchSource = {
  id: string;
  research_id: string;
  title: string;
  url: string;
  domain: string;
  snippet: string | null;
  extracted_content: string | null;
  publication_date: string | null;
  retrieved_at: string;
  source_type: string;
  retrieval_status: string;
  quality_metadata: Record<string, unknown> | null;
  created_at: string;
};

export type ResearchFinding = {
  id: string;
  research_id: string;
  finding_type: string;
  claim: string;
  explanation: string | null;
  confidence_label: string;
  supporting_source_ids: string[];
  created_at: string;
};
