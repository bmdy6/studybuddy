import client from '@/shared/api/client';
import type {
  ChangePasswordRequest,
  LoginRequest,
  LoginResponse,
  RegisterRequest,
  UpdateProfileRequest,
  UserProfile,
} from '@/types';

export const authApi = {
  login: (data: LoginRequest) =>
    client.post<LoginResponse>('/auth/login', data).then((r) => r.data),

  register: (data: RegisterRequest) =>
    client.post<LoginResponse>('/auth/register', data).then((r) => r.data),

  getProfile: () => client.get<UserProfile>('/auth/me').then((r) => r.data),

  updateProfile: (data: UpdateProfileRequest) =>
    client.patch<UserProfile>('/auth/me', data).then((r) => r.data),

  changePassword: (data: ChangePasswordRequest) =>
    client.put('/auth/me/password', data).then((r) => r.data),
};
