import { useReveal } from '../useReveal';
import { loginUrl } from '../LandingApp';

const STEPS = [
  { no: '1', title: '注册账号', desc: '点「开始体验」进入注册，家长或孩子都可以先建号。' },
  { no: '2', title: '填好基础信息', desc: '年级、科目填好后，在对话里提出学习目标，查看并确认计划草案。' },
  { no: '3', title: '开始使用', desc: '出题、答题、看反馈、收摘要，从今天的第一件小事开始。' },
];

export function StartSection() {
  const reveal = useReveal<HTMLElement>();

  return (
    <section className="ld-section" id="start" ref={reveal}>
      <div className="ld-container">
        <p className="ld-kicker">如何开始</p>
        <h2>三步就能用起来</h2>
        <ol className="ld-steps">
          {STEPS.map((step) => (
            <li key={step.no}>
              <span className="ld-step-no">{step.no}</span>
              <h3>{step.title}</h3>
              <p>{step.desc}</p>
            </li>
          ))}
        </ol>

        <div className="ld-beta-card">
          <h3>自托管说明</h3>
          <ul className="ld-beta-list">
            <li>本仓库提供完整客户端、后端和可选微信 Bot，由你自行运行。</li>
            <li>先配置数据库和模型服务，再注册学生账号开始使用。</li>
            <li>源码采用 AGPL-3.0-only；模型和托管费用由你自行承担。</li>
            <li>轻量练习不记入正式错题本和统计，正式考试记录才会进入孩子的错题与学习档案。</li>
          </ul>
          <a className="ld-btn ld-btn-primary ld-btn-lg" href={loginUrl}>
            开始体验
          </a>
        </div>
      </div>
    </section>
  );
}
