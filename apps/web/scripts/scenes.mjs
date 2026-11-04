// In-house scene illustrations (2400 x 1350) in the brand palette. Each function returns an SVG string.
const W = 2400;
const H = 1350;
const wrap = (body, top = "#12305A", bottom = "#0B1B33") =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${top}"/><stop offset="1" stop-color="${bottom}"/></linearGradient></defs><rect width="${W}" height="${H}" fill="url(#sky)"/>${body}</svg>`;
const rects = (items, fill, op = 1) =>
  items
    .map(
      ([x, y, w, h]) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}" opacity="${op}"/>`,
    )
    .join("");
const COLORS = ["#2F74D8", "#00A3A3", "#E69F00", "#8E5BD9", "#6C7A89", "#1F5FBF"];

export const scenes = {
  logistics() {
    let b = `<rect y="900" width="${W}" height="450" fill="#0B1B33"/><rect y="880" width="${W}" height="30" fill="#1F5FBF" opacity=".5"/>`;
    for (let i = 0; i < 3; i++) {
      const x = 260 + i * 700;
      b += `<g fill="none" stroke="#8FC2FF" stroke-width="14"><path d="M${x} 880V300h520M${x + 420} 880V300"/><path d="M${x + 520} 300l-80 60"/></g><rect x="${x + 360}" y="300" width="120" height="70" fill="#00A3A3"/>`;
    }
    for (let r = 0; r < 4; r++)
      for (let c = 0; c < 22; c++)
        b += `<rect x="${60 + c * 106}" y="${960 + r * 80}" width="98" height="72" fill="${COLORS[(r * 7 + c * 3) % 6]}" opacity="${0.55 + ((r + c) % 3) * 0.12}"/>`;
    return wrap(b, "#1F5FBF", "#0B1B33");
  },
  manufacturing() {
    let b = `<rect y="980" width="${W}" height="370" fill="#0B1B33"/>`;
    for (let i = 0; i < 6; i++)
      b += `<path d="M${120 + i * 380} 980V560l190 120V560l0 0v420z" fill="#12305A"/><path d="M${120 + i * 380} 560l190 120v300h-190z" fill="#1B3F73"/>`;
    b += rects(
      [
        [1680, 300, 90, 680],
        [1820, 400, 70, 580],
      ],
      "#12305A",
    );
    for (let i = 0; i < 30; i++)
      b += `<rect x="${140 + i * 74}" y="${820 + (i % 2) * 20}" width="46" height="46" fill="#E69F00" opacity="${0.35 + (i % 4) * 0.12}"/>`;
    b += `<path d="M0 1060H${W}" stroke="#2F74D8" stroke-width="10"/>`;
    return wrap(b, "#2F74D8", "#0B1B33");
  },
  retail() {
    let b = "";
    for (let s = 0; s < 4; s++) {
      const y = 180 + s * 280;
      b += `<rect x="80" y="${y + 200}" width="${W - 160}" height="24" fill="#8E9BB0"/>`;
      for (let i = 0; i < 26; i++)
        b += `<rect x="${110 + i * 87}" y="${y + 70 + (i % 3) * 18}" width="70" height="${130 - (i % 3) * 18}" rx="6" fill="${COLORS[(i + s * 2) % 6]}" opacity=".85"/>`;
    }
    return wrap(b, "#E6EFFB", "#C3CCD9");
  },
  energy() {
    let b = `<circle cx="1700" cy="860" r="170" fill="#E69F00" opacity=".85"/><rect y="1000" width="${W}" height="350" fill="#0B1B33"/>`;
    for (let i = 0; i < 4; i++) {
      const x = 260 + i * 560;
      b += `<g stroke="#0B1B33" stroke-width="12" fill="none"><path d="M${x} 1000L${x + 60} 400L${x + 120} 1000M${x + 20} 760H${x + 100}M${x + 35} 560H${x + 85}M${x - 80} 460H${x + 200}"/></g>`;
      if (i < 3)
        b += `<path d="M${x + 200} 460Q${x + 420} 560 ${x + 640} 460" stroke="#0B1B33" stroke-width="5" fill="none"/>`;
    }
    return wrap(b, "#12305A", "#D55E5E");
  },
  insurance() {
    let b = `<rect y="900" width="${W}" height="450" fill="#12305A"/>`;
    for (let i = 0; i < 4; i++) {
      const x = 300 + i * 460,
        y = 220 + (i % 2) * 90,
        rot = -6 + i * 4;
      b += `<g transform="rotate(${rot} ${x + 160} ${y + 220})"><rect x="${x}" y="${y}" width="340" height="460" rx="12" fill="#FFFFFF"/>${rects(
        [
          [x + 30, y + 40, 200, 18],
          [x + 30, y + 90, 280, 12],
          [x + 30, y + 120, 260, 12],
          [x + 30, y + 150, 240, 12],
        ],
        "#C3CCD9",
      )}<rect x="${x + 30}" y="${y + 230}" width="280" height="170" rx="8" fill="#E6EFFB"/><circle cx="${x + 170}" cy="${y + 315}" r="46" fill="none" stroke="#00A3A3" stroke-width="6" stroke-dasharray="10 8"/><circle cx="${x + 170}" cy="${y + 315}" r="9" fill="#1F5FBF"/></g>`;
    }
    return wrap(b, "#E6EFFB", "#8E9BB0");
  },
  "security-ops"() {
    let b = `<rect y="1000" width="${W}" height="350" fill="#07111F"/>`;
    for (let r = 0; r < 2; r++)
      for (let c = 0; c < 4; c++) {
        const x = 180 + c * 520,
          y = 200 + r * 400;
        b += `<rect x="${x}" y="${y}" width="470" height="340" rx="12" fill="#0E1626" stroke="#243252" stroke-width="6"/><rect x="${x + 18}" y="${y + 18}" width="434" height="304" rx="6" fill="#152038"/>`;
        b += `<path d="M${x + 40} ${y + 260}L${x + 120} ${y + 200}L${x + 200} ${y + 230}L${x + 300} ${y + 120}L${x + 420} ${y + 160}" stroke="${COLORS[(r * 4 + c) % 6]}" stroke-width="8" fill="none"/>`;
        b += rects(
          [
            [x + 40, y + 50, 120, 12],
            [x + 40, y + 80, 200, 10],
          ],
          "#2F74D8",
          0.7,
        );
      }
    return wrap(b, "#12305A", "#07111F");
  },
  "server-room"() {
    let b = "";
    for (let i = 0; i < 9; i++) {
      const x = 80 + i * 260;
      b += `<rect x="${x}" y="140" width="220" height="1100" rx="10" fill="#0E1626" stroke="#243252" stroke-width="5"/>`;
      for (let j = 0; j < 14; j++)
        b += `<rect x="${x + 16}" y="${170 + j * 76}" width="188" height="56" rx="5" fill="#152038"/><circle cx="${x + 36}" cy="${198 + j * 76}" r="7" fill="${(i + j) % 5 === 0 ? "#00A3A3" : "#2F74D8"}"/><rect x="${x + 64}" y="${190 + j * 76}" width="${80 + ((i * j) % 5) * 12}" height="9" rx="4" fill="#243252"/>`;
    }
    return wrap(b, "#0B1B33", "#12305A");
  },
  company() {
    let b = "";
    const pts = [
      [500, 400],
      [1000, 300],
      [1500, 480],
      [1900, 360],
      [800, 820],
      [1300, 900],
      [1800, 860],
      [300, 960],
    ];
    pts.forEach(([x, y], i) =>
      pts.slice(i + 1).forEach(([x2, y2], j) => {
        if ((i + j) % 2 === 0)
          b += `<path d="M${x} ${y}L${x2} ${y2}" stroke="#2F74D8" stroke-width="4" opacity=".6"/>`;
      }),
    );
    pts.forEach(
      ([x, y], i) =>
        (b += `<circle cx="${x}" cy="${y}" r="${46 + (i % 3) * 14}" fill="${COLORS[i % 6]}" opacity=".9"/><circle cx="${x}" cy="${y}" r="14" fill="#fff"/>`),
    );
    return wrap(b, "#E6EFFB", "#C3CCD9");
  },
  "article-ambiguity": () => articleScene("A"),
  "article-linking": () => articleScene("B"),
  "article-feeds": () => articleScene("C"),
  "article-measuring": () => articleScene("D"),
  "article-exposure": () => articleScene("E"),
  "article-responsible": () => articleScene("F"),
};

function articleScene(k) {
  const i = "ABCDEF".indexOf(k);
  let b = "";
  for (let n = 0; n < 7; n++)
    b += `<circle cx="${((n * 397 + i * 211) % 2200) + 100}" cy="${((n * 263 + i * 137) % 1000) + 150}" r="${120 + ((n + i) % 4) * 40}" fill="none" stroke="${COLORS[(n + i) % 6]}" stroke-width="10" stroke-dasharray="${24 + i * 6} 18" opacity=".8"/>`;
  b += `<circle cx="1200" cy="675" r="70" fill="#fff"/><circle cx="1200" cy="675" r="26" fill="#2F74D8"/>`;
  return wrap(b, "#12305A", "#0B1B33");
}
