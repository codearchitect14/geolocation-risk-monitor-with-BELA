/** In-house illustrations in the brand palette. All are decorative and hidden from assistive technology. */
const C = {
  ink: "#0B1B33",
  navy: "#12305A",
  blue: "#2F74D8",
  blue6: "#1F5FBF",
  pale: "#E6EFFB",
  teal: "#00A3A3",
  line: "#DDE3EC",
  warn: "#E69F00",
  red: "#D55E5E",
};

function Svg({
  children,
  className,
  box = "0 0 240 140",
}: {
  children: React.ReactNode;
  className?: string;
  box?: string;
}) {
  return (
    <svg viewBox={box} className={className} aria-hidden="true" focusable="false" fill="none">
      {children}
    </svg>
  );
}

export function SameNameDifferentPlace({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <rect x="8" y="12" width="104" height="116" rx="10" fill={C.pale} />
      <rect x="128" y="12" width="104" height="116" rx="10" fill={C.pale} />
      <path d="M20 100c14-20 30-8 44-26s26-6 36-24" stroke={C.line} strokeWidth="6" strokeLinecap="round" />
      <path d="M140 96c14 6 24-14 40-6s24-22 40-14" stroke={C.line} strokeWidth="6" strokeLinecap="round" />
      <circle cx="60" cy="62" r="9" fill={C.blue6} />
      <circle cx="60" cy="62" r="3.5" fill="#fff" />
      <circle cx="180" cy="58" r="9" fill={C.teal} />
      <circle cx="180" cy="58" r="3.5" fill="#fff" />
      <rect x="30" y="102" width="60" height="14" rx="7" fill="#fff" />
      <rect x="150" y="102" width="60" height="14" rx="7" fill="#fff" />
      <rect x="38" y="107" width="44" height="4" rx="2" fill={C.ink} />
      <rect x="158" y="107" width="44" height="4" rx="2" fill={C.ink} />
      <path d="M116 70h8" stroke={C.ink} strokeWidth="3" strokeLinecap="round" />
      <path d="M116 62h8" stroke={C.ink} strokeWidth="3" strokeLinecap="round" />
    </Svg>
  );
}

export function LocalReportsFirst({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <rect x="16" y="14" width="120" height="30" rx="8" fill={C.pale} />
      <rect x="26" y="25" width="70" height="5" rx="2.5" fill={C.blue6} />
      <rect x="26" y="34" width="40" height="4" rx="2" fill={C.line} />
      <rect x="48" y="54" width="120" height="30" rx="8" fill="#fff" stroke={C.line} />
      <rect x="58" y="65" width="76" height="5" rx="2.5" fill={C.ink} />
      <rect x="58" y="74" width="46" height="4" rx="2" fill={C.line} />
      <rect x="84" y="94" width="140" height="30" rx="8" fill="#fff" stroke={C.line} />
      <rect x="94" y="105" width="96" height="5" rx="2.5" fill={C.ink} />
      <rect x="94" y="114" width="56" height="4" rx="2" fill={C.line} />
      <circle cx="152" cy="29" r="9" fill={C.teal} />
      <path d="M152 24v6l4 2" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
      <path d="M184 52l12 12" stroke={C.warn} strokeWidth="3" strokeLinecap="round" opacity=".0" />
    </Svg>
  );
}

export function AlertsWithoutContext({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <rect x="20" y="20" width="200" height="30" rx="8" fill="#fff" stroke={C.line} />
      <circle cx="38" cy="35" r="7" fill={C.red} />
      <rect x="54" y="30" width="110" height="5" rx="2.5" fill={C.ink} />
      <rect x="54" y="39" width="60" height="4" rx="2" fill={C.line} />
      <rect x="20" y="60" width="200" height="30" rx="8" fill="#fff" stroke={C.line} />
      <circle cx="38" cy="75" r="7" fill={C.red} />
      <rect x="54" y="70" width="90" height="5" rx="2.5" fill={C.ink} />
      <rect x="54" y="79" width="70" height="4" rx="2" fill={C.line} />
      <rect x="20" y="100" width="200" height="30" rx="8" fill="#fff" stroke={C.line} />
      <circle cx="38" cy="115" r="7" fill={C.red} />
      <rect x="54" y="110" width="124" height="5" rx="2.5" fill={C.ink} />
      <rect x="54" y="119" width="44" height="4" rx="2" fill={C.line} />
      <path
        d="M190 66l14 14m0-14l-14 14"
        stroke={C.warn}
        strokeWidth="3"
        strokeLinecap="round"
        opacity=".0"
      />
    </Svg>
  );
}

export function StepSites({ className }: { className?: string }) {
  return (
    <Svg className={className} box="0 0 200 110">
      <rect x="10" y="10" width="180" height="90" rx="10" fill={C.pale} />
      {[
        [40, 36],
        [92, 62],
        [140, 40],
        [120, 78],
        [60, 74],
      ].map(([x, y]) => (
        <g key={`${x}-${y}`}>
          <circle cx={x} cy={y} r="8" fill={C.blue6} />
          <rect x={(x as number) - 3} y={(y as number) - 3} width="6" height="6" fill="#fff" />
        </g>
      ))}
      <path
        d="M40 36L92 62L140 40M92 62L120 78M92 62L60 74"
        stroke={C.blue}
        strokeWidth="1.5"
        strokeDasharray="4 3"
      />
    </Svg>
  );
}
export function StepFeeds({ className }: { className?: string }) {
  return (
    <Svg className={className} box="0 0 200 110">
      <rect x="10" y="12" width="64" height="86" rx="8" fill={C.pale} />
      {[26, 44, 62, 80].map((y) => (
        <rect
          key={y}
          x="20"
          y={y}
          width={y % 36 === 8 ? 36 : 44}
          height="6"
          rx="3"
          fill={y === 44 ? C.blue6 : C.line}
        />
      ))}
      <path d="M82 55h40" stroke={C.ink} strokeWidth="2.5" strokeLinecap="round" />
      <path
        d="M114 47l8 8-8 8"
        stroke={C.ink}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="154" cy="55" r="32" fill={C.pale} />
      <path d="M132 55a22 22 0 0 1 44 0" stroke={C.teal} strokeWidth="3" />
      <path d="M140 55a14 14 0 0 1 28 0" stroke={C.blue6} strokeWidth="3" />
      <circle cx="154" cy="55" r="4" fill={C.ink} />
    </Svg>
  );
}
export function StepLink({ className }: { className?: string }) {
  return (
    <Svg className={className} box="0 0 200 110">
      <rect x="10" y="10" width="180" height="90" rx="10" fill={C.pale} />
      <circle
        cx="110"
        cy="56"
        r="34"
        stroke={C.teal}
        strokeWidth="2"
        strokeDasharray="5 4"
        fill="#00A3A31A"
      />
      <circle cx="110" cy="56" r="10" fill={C.blue6} />
      <circle cx="110" cy="56" r="4" fill="#fff" />
      <circle cx="68" cy="38" r="7" fill={C.ink} />
      <circle cx="140" cy="78" r="7" fill={C.ink} />
      <rect x="22" y="76" width="70" height="14" rx="7" fill="#fff" />
      <rect x="30" y="81" width="44" height="4" rx="2" fill={C.ink} />
    </Svg>
  );
}
export function StepAlert({ className }: { className?: string }) {
  return (
    <Svg className={className} box="0 0 200 110">
      <rect x="24" y="12" width="152" height="40" rx="8" fill="#fff" stroke={C.line} />
      <circle cx="46" cy="32" r="9" fill={C.red} />
      <path d="M46 27v6" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="46" cy="37" r="1.3" fill="#fff" />
      <rect x="64" y="25" width="90" height="5" rx="2.5" fill={C.ink} />
      <rect x="64" y="35" width="56" height="4" rx="2" fill={C.line} />
      <rect x="24" y="62" width="152" height="36" rx="8" fill={C.pale} />
      <rect x="38" y="74" width="100" height="5" rx="2.5" fill={C.blue6} />
      <rect x="38" y="84" width="64" height="4" rx="2" fill={C.line} />
    </Svg>
  );
}

/** Event location with an uncertainty circle and assets inside and outside it. */
export function MapRadius({ className }: { className?: string }) {
  return (
    <Svg className={className} box="0 0 480 300">
      <rect width="480" height="300" rx="14" fill={C.pale} />
      <path d="M0 230C80 190 120 250 200 220S330 150 480 190" stroke="#fff" strokeWidth="14" />
      <path d="M60 0C90 80 70 150 120 300" stroke="#fff" strokeWidth="10" />
      <circle
        cx="250"
        cy="140"
        r="96"
        fill="#00A3A31F"
        stroke={C.teal}
        strokeWidth="2"
        strokeDasharray="7 5"
      />
      <circle cx="250" cy="140" r="9" fill={C.red} stroke="#fff" strokeWidth="2.5" />
      <path d="M250 140L330 92" stroke={C.ink} strokeWidth="1.5" strokeDasharray="3 3" />
      <text x="296" y="108" fontSize="12" fontFamily="Inter Variable, system-ui, sans-serif" fill={C.ink}>
        42 km
      </text>
      {[
        [318, 96, true],
        [190, 188, true],
        [400, 230, false],
        [96, 70, false],
      ].map(([x, y, hit]) => (
        <g key={`${x}-${y}`}>
          <rect
            x={(x as number) - 8}
            y={(y as number) - 8}
            width="16"
            height="16"
            rx="3"
            fill={hit ? C.blue6 : "#8E9BB0"}
            stroke="#fff"
            strokeWidth="2"
          />
        </g>
      ))}
      <g fontFamily="Inter Variable, system-ui, sans-serif" fontSize="12" fill={C.ink}>
        <text x="338" y="72">
          Asset inside
        </text>
        <text x="204" y="214">
          Asset inside
        </text>
        <text x="342" y="256">
          Outside, no alert
        </text>
      </g>
    </Svg>
  );
}

/** Pipeline overview for the platform page. */
export function PipelineDiagram({ className }: { className?: string }) {
  const stages = ["Ingest", "Link places", "Detect incidents", "Score exposure", "Alert and brief"];
  return (
    <svg
      viewBox="0 0 960 150"
      className={className}
      role="img"
      aria-label="Pipeline: ingest, link places, detect incidents, score exposure, alert and brief"
    >
      {stages.map((s, i) => (
        <g key={s} transform={`translate(${i * 192},20)`}>
          <rect
            width="168"
            height="80"
            rx="12"
            fill={i === 1 || i === 3 ? "#E6EFFB" : "#FFFFFF"}
            stroke={C.line}
          />
          <text
            x="84"
            y="36"
            textAnchor="middle"
            fontSize="12"
            fontFamily="Inter Variable, system-ui, sans-serif"
            fill="#5F6E85"
          >{`Step ${i + 1}`}</text>
          <text
            x="84"
            y="58"
            textAnchor="middle"
            fontSize="16"
            fontWeight="600"
            fontFamily="Inter Variable, system-ui, sans-serif"
            fill={C.ink}
          >
            {s}
          </text>
          {i < stages.length - 1 ? (
            <path
              d="M172 40h16m-6-5l6 5-6 5"
              stroke={C.blue6}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ) : null}
        </g>
      ))}
      <text
        x="480"
        y="132"
        textAnchor="middle"
        fontSize="13"
        fontFamily="Inter Variable, system-ui, sans-serif"
        fill="#5F6E85"
      >
        Stored results are reused: linking and geolocation run once at ingestion
      </text>
    </svg>
  );
}
