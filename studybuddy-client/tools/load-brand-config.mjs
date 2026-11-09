import fs from 'node:fs';
import path from 'node:path';
import { parse } from 'yaml';

const configPath = path.resolve(process.cwd(), '..', 'studybuddy-backend', 'config.yaml');

export function loadBrandConfig(filePath = configPath) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`配置文件不存在: ${filePath}`);
  }
  const root = parse(fs.readFileSync(filePath, 'utf8'));
  const name = root?.brand?.name;
  const nameEn = root?.brand?.name_en;
  if (typeof name !== 'string' || name.trim().length === 0) {
    throw new Error('config.yaml 的 brand.name 必须是非空字符串');
  }
  if (typeof nameEn !== 'string') {
    throw new Error('config.yaml 的 brand.name_en 必须是字符串');
  }
  return Object.freeze({ name: name.trim(), nameEn: nameEn.trim() });
}
