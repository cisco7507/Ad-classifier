type BrandLogoProps = {
  className?: string;
};

const bellMediaLogoUrl =
  'https://www.bellmedia.ca/lede/wp-content/uploads/2016/10/bell_media_en_white.png';

export function BrandLogo({ className = '' }: BrandLogoProps) {
  return (
    <div className={`scenalyze-brand-card ${className}`.trim()}>
      <div className="scenalyze-brand-bell">
        <img src={bellMediaLogoUrl} alt="Bell Media" />
      </div>

      <div className="scenalyze-brand-divider" aria-hidden="true" />

      <div className="scenalyze-brand-block">
        <div className="scenalyze-brand-mark" aria-hidden="true">
          <div className="scenalyze-brand-ring" />
          <div className="scenalyze-brand-core">
            <span className="scenalyze-brand-letter">B</span>
            <div className="scenalyze-brand-scan" />
          </div>
        </div>

        <div className="scenalyze-brand-text">
          <span className="scenalyze-brand-name">Scenalyze</span>
          <span className="scenalyze-brand-tagline">Intelligence meets video. Every frame tells a story.</span>
        </div>
      </div>
    </div>
  );
}
