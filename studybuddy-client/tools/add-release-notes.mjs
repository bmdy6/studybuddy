import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const releaseDir = fileURLToPath(new URL('../release/', import.meta.url));
const notes = [
  '1. 修复学生答题页右侧答题卡题号贴边/溢出问题。',
  '2. 调整答题卡题号格为固定尺寸并居中排列，50 题试卷也不会顶出卡片。',
  '3. 答题卡 hover 从放大改为轻微上浮，避免边缘题号被裁切。',
].join('\n');

function upsertReleaseNotes(fileName) {
  const filePath = join(releaseDir, fileName);
  let content = readFileSync(filePath, 'utf8');
  content = content.replace(/\nreleaseNotes:\s*\|-[\s\S]*?(?=\n[a-zA-Z][\w-]*:|$)/m, '');
  content = content.replace(/\nreleaseNotes:\s*\|[\s\S]*?(?=\n[a-zA-Z][\w-]*:|$)/m, '');
  const block = `releaseNotes: |-\n${notes
    .split('\n')
    .map((line) => `  ${line}`)
    .join('\n')}\n`;
  writeFileSync(filePath, `${content.trimEnd()}\n${block}`, 'utf8');
}

for (const fileName of ['latest.yml', 'latest-mac.yml']) {
  upsertReleaseNotes(fileName);
}
