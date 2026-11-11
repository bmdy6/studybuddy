import { useReveal } from '../useReveal';
import { loginUrl } from '../LandingApp';

export function FinalCtaSection() {
  const reveal = useReveal<HTMLElement>();

  return (
    <section className="ld-cta" ref={reveal}>
      <div className="ld-cta-inner">
        <h2>从今天的一件小事开始</h2>
        <p>不追求一次学会，只保证每天真实发生。</p>
        <a className="ld-btn ld-btn-light ld-btn-lg" href={loginUrl}>
          开始体验
        </a>
      </div>
    </section>
  );
}
