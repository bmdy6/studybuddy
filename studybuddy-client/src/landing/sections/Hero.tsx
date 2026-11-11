import { useReveal } from '../useReveal';
import { loginUrl } from '../LandingApp';

export function HeroSection() {
  const reveal = useReveal<HTMLElement>();

  return (
    <section className="ld-hero" ref={reveal}>
      <div className="ld-hero-copy">
        <p className="ld-kicker">家庭轻量辅导 · 双向陪伴</p>
        <h1>
          家长出题，孩子答题，
          <br />
          AI 帮你把错题和反馈整理好
        </h1>
        <p className="ld-hero-sub">
          孩子打开就知道今天该学什么，做错的题自动进错题本；
          你随时能看到孩子真实的学习情况，不用天天追着问。
        </p>
        <div className="ld-hero-actions">
          <a className="ld-btn ld-btn-primary ld-btn-lg" href={loginUrl}>
            开始体验
          </a>
          <a className="ld-btn ld-btn-ghost ld-btn-lg" href="#start">
            如何开始
          </a>
        </div>
        <p className="ld-hero-note">自己运行，注册后开始学习</p>
      </div>

      <div className="ld-hero-shots" aria-label="知了产品真实页面截图">
        <div className="ld-shot ld-shot--back">
          <img
            src="shots/notes.png"
            alt="知了笔记页面截图"
            width={390}
            height={844}
            decoding="async"
          />
        </div>
        <div className="ld-shot ld-shot--back">
          <img
            src="shots/task.png"
            alt="知了任务会话页面截图"
            width={390}
            height={844}
            decoding="async"
          />
        </div>
        <div className="ld-shot ld-shot--front">
          <img
            src="shots/home.png"
            alt="知了学习首页页面截图"
            width={390}
            height={844}
            fetchPriority="high"
          />
        </div>
      </div>
    </section>
  );
}
