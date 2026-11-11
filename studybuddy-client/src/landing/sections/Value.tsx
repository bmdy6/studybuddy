import { useReveal } from '../useReveal';

const PARENT_POINTS = [
  { title: '出题不用找题', desc: '想让孩子练什么，直接说就行，AI 帮你出题、出试卷。' },
  { title: '批改不用对答案', desc: '客观题自动批改，还能识别敷衍作答，你不用盯着对答案。' },
  { title: '错题自动成册', desc: '做错的题按学科、知识点、错因自动整理，随时能翻。' },
  { title: '每天一份真实摘要', desc: '孩子每天学了什么，微信里就能看到，都来自真实作答。' },
];

const CHILD_POINTS = [
  { title: '打开就知道学什么', desc: '今天的计划排好了，不用自己纠结先做哪件事。' },
  { title: '答完当场有反馈', desc: '对错、错在哪、怎么改，AI 当场讲清楚。' },
  { title: '错题有地方归档', desc: '做错的题自动进错题本，复习的时候随时回头翻。' },
  { title: '不会的直接问', desc: '卡住了就开口问，计划、资料、题目都能从对话开始。' },
];

export function ValueSection() {
  const reveal = useReveal<HTMLElement>();

  return (
    <section className="ld-section ld-section--alt" id="value" ref={reveal}>
      <div className="ld-container">
        <p className="ld-kicker">一家人的学习，各取所需</p>
        <h2>家长省心，孩子顺手</h2>
        <div className="ld-value-grid">
          <article className="ld-value-card">
            <h3>家长这一侧</h3>
            <ul className="ld-point-list">
              {PARENT_POINTS.map((p) => (
                <li key={p.title}>
                  <strong>{p.title}</strong>
                  <span>{p.desc}</span>
                </li>
              ))}
            </ul>
          </article>
          <article className="ld-value-card">
            <h3>孩子这一侧</h3>
            <ul className="ld-point-list">
              {CHILD_POINTS.map((p) => (
                <li key={p.title}>
                  <strong>{p.title}</strong>
                  <span>{p.desc}</span>
                </li>
              ))}
            </ul>
          </article>
        </div>
      </div>
    </section>
  );
}
