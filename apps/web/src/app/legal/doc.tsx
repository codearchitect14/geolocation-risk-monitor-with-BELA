export type LegalSection = { heading: string; body: string[] };

export function Doc({ sections }: { sections: LegalSection[] }) {
  return (
    <div className="prose-article">
      {sections.map((s) => (
        <section key={s.heading}>
          <h2>{s.heading}</h2>
          {s.body.map((p) => (
            <p key={p}>{p}</p>
          ))}
        </section>
      ))}
    </div>
  );
}
