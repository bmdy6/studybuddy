import { useReveal } from '../useReveal';

const LOOP_STEPS = [
  {
    no: '01',
    title: '今天学什么',
    desc: 'AI 按你定的计划，给孩子排出今天要做的事，打开就知道。',
  },
  {
    no: '02',
    title: '做题、对答案',
    desc: '孩子按计划答题，答完 AI 当场批改，客观题自动判，不靠对答案。',
  },
  {
    no: '03',
    title: 'AI 讲错题',
    desc: '错在哪、为什么错、下一步怎么练，AI 整理成一条条看得懂的反馈。',
  },
  {
    no: '04',
    title: '错题进本子',
    desc: '做错的题自动归档进错题本，按学科和知识点整理，复习时随时翻。',
  },
  {
    no: '05',
    title: '家长收到摘要',
    desc: '孩子今天真实学了什么，家长在微信里收到一份当天的学习记录。',
  },
];

export function LoopSection() {
  const reveal = useReveal<HTMLElement>();

  return (
    <section className="ld-section" id="loop" ref={reveal}>
      <div className="ld-container">
        <p className="ld-kicker">一天的陪伴</p>
        <h2>从「今天学什么」开始，到「今天学了什么」结束</h2>
        <p className="ld-section-lead">
          不是把题目丢给孩子就不管了——每一环都有 AI 接着，家长只需要看一眼。
        </p>
        <ol className="ld-loop">
          {LOOP_STEPS.map((step) => (
            <li key={step.no} className="ld-loop-step">
              <span className="ld-loop-no">{step.no}</span>
              <div className="ld-loop-body">
                <h3>{step.title}</h3>
                <p>{step.desc}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
