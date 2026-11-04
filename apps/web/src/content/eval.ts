/** Figures copied from docs/eval/report.md (test split). A unit test checks them against public/metrics.json. */
export const evalRows = [
  {
    id: "S1",
    name: "Largest-population GeoNames match",
    acc25: "41.6%",
    acc161: "43.8%",
    median: "2.1",
    mean: "2,129",
    amb161: "45.2%",
  },
  {
    id: "S2",
    name: "GeoNames with country and region context",
    acc25: "48.1%",
    acc161: "50.5%",
    median: "0.8",
    mean: "1,703",
    amb161: "58.6%",
  },
  {
    id: "S4",
    name: "Entity linker alone",
    acc25: "25.9%",
    acc161: "29.8%",
    median: "0.4",
    mean: "390",
    amb161: "26.1%",
  },
  {
    id: "S5",
    name: "Linker with type filter, routing, gazetteer fallback and context re-ranking",
    acc25: "58.6%",
    acc161: "65.7%",
    median: "0.2",
    mean: "513",
    amb161: "69.5%",
  },
  {
    id: "S6",
    name: "S5 with local model adjudication (shipped configuration)",
    acc25: "58.7%",
    acc161: "65.8%",
    median: "0.2",
    mean: "514",
    amb161: "69.5%",
  },
] as const;

export const byCorpus = [
  { corpus: "GeoVirus", s1: "1.3%", s6: "73.0%" },
  { corpus: "GeoWebNews", s1: "58.3%", s6: "59.0%" },
  { corpus: "LGL", s1: "57.8%", s6: "67.0%" },
  { corpus: "TR-News", s1: "71.0%", s6: "69.8%" },
  { corpus: "WikToR (sample)", s1: "15.6%", s6: "61.9%" },
] as const;

export const failures = [
  { outcome: "Located within 25 km", share: "58.7%" },
  { outcome: "Mention not detected", share: "15.1%" },
  { outcome: "Located at the wrong place", share: "11.0%" },
  { outcome: "Detected but not resolved", share: "8.1%" },
  { outcome: "Located within 161 km but not 25 km", share: "7.1%" },
] as const;
