export interface ApiReviewComment {
  id: string;
  project_id: string;
  task_id: string;
  author_user_id: string;
  body: string;
  file_path: string;
  line_number: number | null;
  resolved: boolean;
  created_at: string;
}

export interface ReviewCommentCreatePayload {
  body: string;
  file_path?: string;
  line_number?: number | null;
}
