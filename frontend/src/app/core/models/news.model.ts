/** News, sentiment & anomaly models */

export interface SentimentResult {
  score: number;
  label: string;
  event_tags: string[];
  keywords_found: string[];
}

export interface AnomalyAlert {
  type: string;
  ticker: string;
  severity: string;
  value: number;
  threshold: number;
  message: string;
}

export interface NewsArticle {
  title: string;
  source: string;
  url: string;
  published_at: string;
  summary?: string;
  sentiment?: SentimentResult;
}
