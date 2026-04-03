/** Authentication models */

export interface AuthToken {
  access_token: string;
  token_type: string;
  expires_in?: number;
}

export interface UserSession {
  token: string | null;
  isAuthenticated: boolean;
}
