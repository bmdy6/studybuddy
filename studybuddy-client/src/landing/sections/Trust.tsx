import { useReveal } from '../useReveal';

const TRUST_POINTS = [
  {
    title: '只记录真实发生的事',
    desc: '你看到的错题、学习记录都来自孩子真实的作答。AI 整理的内容会标明来源，重要内容需要你确认后才会保存。',
  },
  {
    title: '学习数据由你自托管',
    desc: '学习记录保存在你配置的数据库中。调用模型、OCR 或微信时，相关内容会发送给你配置的服务，请自行确认其隐私政策。',
  },
  {
    title: '不催、不逼、不制造焦虑',
    desc: '知了不做成绩排名、不推「再不学就晚了」的提醒，按孩子自己的节奏来。',
  },
];

const FAQS = [
  {
    q: '怎么开始使用？',
    a: '按仓库 README 在自己的电脑或服务器启动，再注册账号使用。',
  },
  {
    q: '适合多大的孩子？',
    a: '主要面向小学到初中的家庭。填写年级和科目后，AI 会按孩子的情况生成学习安排，也可以随时调整。',
  },
  {
    q: '孩子的数据安全吗？',
    a: '数据由部署者管理；模型调用和微信推送需要外部服务。AI 整理内容保留来源，关键结论仍需核对。',
  },
  {
    q: '使用有什么成本？',
    a: '源码开源，自托管和模型服务的费用由使用者承担。',
  },
];

export function TrustSection() {
  const reveal = useReveal<HTMLElement>();

  return (
    <section className="ld-section ld-section--alt" id="trust" ref={reveal}>
      <div className="ld-container">
        <p className="ld-kicker">信任</p>
        <h2>我们把「真实」放在第一位</h2>
        <div className="ld-trust-grid">
          {TRUST_POINTS.map((t) => (
            <article key={t.title} className="ld-trust-card">
              <h3>{t.title}</h3>
              <p>{t.desc}</p>
            </article>
          ))}
        </div>

        <div className="ld-faq" id="faq">
          <h3>常见问题</h3>
          {FAQS.map((faq) => (
            <details key={faq.q} className="ld-faq-item">
              <summary>{faq.q}</summary>
              <p>{faq.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
