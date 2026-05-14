import React from 'react';

function Macros({ m }) {
  if (!m) return null;
  return (
    <div className="meta-sans tabular flex flex-wrap gap-x-3 mt-1">
      {m.protein && (
        <span>
          <strong className="text-ink">P</strong> {m.protein}
        </span>
      )}
      {m.carbs && (
        <span>
          <strong className="text-ink">C</strong> {m.carbs}
        </span>
      )}
      {m.fat && (
        <span>
          <strong className="text-ink">F</strong> {m.fat}
        </span>
      )}
      {m.calories && (
        <span>
          <strong className="text-ink">{m.calories}</strong>
        </span>
      )}
    </div>
  );
}

export default function Nutrition({ data }) {
  if (!data?.available) return null;
  const meals = data.meals || [];

  return (
    <section>
      <header className="rule-after mb-3">
        <div className="section-eyebrow">Recipe & Table</div>
        <h3 className="headline text-[1.35rem] mt-1">Today's Menu</h3>
      </header>

      <ul className="divide-y rule-thin border-t rule-thin border-b">
        {meals.map((m) => (
          <li key={m.category} className="py-2">
            <div className="meta-sans uppercase tracking-wider">{m.category}</div>
            <div className="headline text-[1.05rem] leading-tight mt-0.5">{m.title}</div>
            {m.components?.length > 0 && (
              <div className="body-serif text-[13.5px] mt-0.5 text-inksoft italic">
                {m.components.slice(0, 3).join(' · ')}
              </div>
            )}
            <Macros m={m.macros} />
          </li>
        ))}
      </ul>

      {data.total_calories_est && (
        <p className="byline mt-3">
          Day estimated at ~{data.total_calories_est.toLocaleString()} kcal across {meals.length}{' '}
          meal{meals.length === 1 ? '' : 's'}.
        </p>
      )}
    </section>
  );
}
