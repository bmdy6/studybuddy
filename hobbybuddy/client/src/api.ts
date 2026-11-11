import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8002';

export interface RegisterResult {
  user_id: number;
  username: string;
  display_name: string;
}

export interface LoginResult {
  access_token: string;
  token_type: string;
  user_id: number;
  username: string;
}

export interface ChatResult {
  reply: string;
}

const http = axios.create({ baseURL: API_BASE, timeout: 90000 });

export async function register(
  username: string,
  password: string
): Promise<RegisterResult> {
  const resp = await http.post<RegisterResult>('/api/auth/register', {
    username,
    password,
  });
  return resp.data;
}

export async function login(
  username: string,
  password: string
): Promise<LoginResult> {
  const resp = await http.post<LoginResult>('/api/auth/login', {
    username,
    password,
  });
  return resp.data;
}

export async function chat(
  message: string,
  token: string
): Promise<ChatResult> {
  const resp = await http.post<ChatResult>(
    '/api/chat/',
    { message },
    { headers: { Authorization: `Bearer ${token}` } }
  );
  return resp.data;
}
