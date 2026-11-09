export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  password: string;
}

export interface RegisterFormValues extends RegisterRequest {
  confirmPassword: string;
}

export interface ChildInfo {
  id: number;
  display_name: string;
  mode: 'study' | 'hobby';
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user_id: number;
  /** 后端返回的角色；'teacher' 为阶段二迁移前的过渡值，前端会映射成 'parent' */
  role: 'parent' | 'student' | 'teacher';
  display_name: string;
  avatar: string | null;
  mode: 'study' | 'hobby'; // study=学习(默认) / hobby=兴趣爱好
  children: ChildInfo[]; // parent 登录返回绑定学生；student 为空数组
}

/** 当前用户信息（GET /auth/me） */

export interface UserProfile {
  user_id: number;
  username: string;
  role: string;
  display_name: string;
  avatar: string | null;
  mode: 'study' | 'hobby';
}

/** 改个人资料（PATCH /auth/me） */

export interface UpdateProfileRequest {
  display_name?: string;
  avatar?: string;
  mode?: 'study' | 'hobby';
}

/** 改密码（PUT /auth/me/password） */

export interface ChangePasswordRequest {
  old_password: string;
  new_password: string;
}

// === Exam ===
