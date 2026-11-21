export interface ApiNotification {
  id: string;
  type: string;
  title: string;
  body: string;
  link_url: string;
  read_at: string | null;
  created_at: string;
}
