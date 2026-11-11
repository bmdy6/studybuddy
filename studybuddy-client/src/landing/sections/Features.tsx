import { useReveal } from '../useReveal';

const FEATURES = [
  {
    title: '学习计划',
    desc: '今天该做什么，孩子一打开就知道；计划先出草案，确认后才执行。',
  },
  {
    title: '试卷与批改',
    desc: '家长出题、孩子作答，客观题自动批改，还能识别敷衍作答。',
  },
  {
    title: '错题本',
    desc: '按学科、知识点、错因整理错题，复习不再大海捞针。',
  },
  {
    title: '学习笔记',
    desc: 'AI 把错题讲解放进笔记，孩子确认后才会保存，不把 AI 总结当事实。',
  },
  {
    title: '素材识别',
    desc: '拍下资料上传，AI 识别整理，标注来源和置信度，人工确认优先。',
  },
  {
    title: '每日记录',
    desc: '学习事实按日期归档，AI 摘要标明来源，不编造、不夸大。',
  },
];

export function FeaturesSection() {
  const reveal = useReveal<HTMLElement>();

  return (
    <section className="ld-section ld-section--alt" id="features" ref={reveal}>
      <div className="ld-container">
        <p className="ld-kicker">已经上线的能力</p>
        <h2>该有的功能都有，克制不堆砌</h2>
        <div className="ld-feature-grid">
          {FEATURES.map((f) => (
            <article key={f.title} className="ld-feature-card">
              <h3>{f.title}</h3>
              <p>{f.desc}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
