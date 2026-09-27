export function PageHead({ kicker, title, meta }: { kicker: string; title: string; meta?: string }) {
  return (
    <div className="page-head">
      <div>
        <span className="kicker">{kicker}</span>
        <h1>{title}</h1>
      </div>
      {meta && <span className="meta">{meta}</span>}
    </div>
  );
}
