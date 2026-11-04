import type { FaqItem } from "@/components/ui/accordion";
import { metrics, pct, points } from "@/lib/metrics";

export type NavItem = { title: string; href: string; description: string; icon: string };

export const platformNav: NavItem[] = [
  {
    title: "Ingestion",
    href: "/platform#ingestion",
    description: "News and public hazard feeds in one stream.",
    icon: "Rss",
  },
  {
    title: "Place linking",
    href: "/platform#place-linking",
    description: "Names in text become places with coordinates.",
    icon: "MapPin",
  },
  {
    title: "Incidents",
    href: "/platform#incidents",
    description: "Reports grouped, typed and located with uncertainty.",
    icon: "Siren",
  },
  {
    title: "Exposure scoring",
    href: "/platform#exposure",
    description: "Distance, uncertainty and criticality per asset.",
    icon: "Target",
  },
  {
    title: "Alerts and briefings",
    href: "/platform#alerts",
    description: "Rules, watch zones and scheduled summaries.",
    icon: "BellRing",
  },
  {
    title: "API",
    href: "/platform#api",
    description: "Upload assets, read alerts and locate text.",
    icon: "Braces",
  },
];

export type Solution = {
  slug: string;
  title: string;
  summary: string;
  icon: string;
  problem: string;
  approach: string[];
  workflow: { title: string; body: string }[];
  faq: FaqItem[];
};

export const solutions: Solution[] = [
  {
    slug: "logistics-control-tower",
    title: "Logistics control tower",
    summary: "Watch ports, terminals, depots and lanes against live reports.",
    icon: "Container",
    problem:
      "A control tower tracks hundreds of facilities across many countries. Reports about a port closure, a flooded road or a plant fire appear in local outlets first and use local names. By the time a duplicate story reaches a shared inbox, the shipment schedule has already been affected.",
    approach: [
      "Register terminals, depots, warehouses and crossing points as assets with a criticality rating, or upload them from a spreadsheet with a guided column mapping.",
      "The platform links place names in incoming reports to the gazetteer, so a report about one named harbor is matched to the right harbor and not to a town with the same name.",
      "Each incident is compared with every asset by distance and by the uncertainty of its location. Only incidents that can plausibly affect an asset raise an alert.",
      "Teams acknowledge, assign and resolve alerts in one place, and receive a daily briefing grouped by facility group.",
    ],
    workflow: [
      {
        title: "Load the network",
        body: "Upload a facility list. Ambiguous rows are held for review instead of being placed silently.",
      },
      {
        title: "Receive an alert",
        body: "An alert states the incident, the asset, the distance and how certain the location is.",
      },
      {
        title: "Act and record",
        body: "Acknowledge, assign, add a note and close with a reason. Every step is kept in the audit log.",
      },
    ],
    faq: [
      {
        q: "Does the platform track vessels or shipments?",
        a: "No. It monitors the places you register and reports near them. It does not track vessels, vehicles or cargo.",
      },
      {
        q: "How are routes handled?",
        a: "A route can be registered as a line asset, and distance is measured to its nearest point. Watch zones drawn around corridors and the facilities along a route work together with it.",
      },
      {
        q: "What if a report names a facility we have not registered?",
        a: "Incidents are still shown on the map. Only registered assets and watch zones produce alerts.",
      },
    ],
  },
  {
    slug: "corporate-security",
    title: "Corporate security",
    summary: "Give security operations a single picture of events near people and sites.",
    icon: "ShieldCheck",
    problem:
      "Security teams monitor feeds from many providers. Each has its own geography, and the same event arrives several times with different place names. Analysts spend the first minutes of every incident deciding whether it is near an office, a plant or a hotel.",
    approach: [
      "Offices, plants and data centers are registered once. Locations stay inside the tenant and are never used in platform analytics.",
      "Duplicate reports are grouped into one incident with a confidence rating and the list of original sources.",
      "Incident detail shows the uncertainty circle, linked places, a timeline and similar past incidents within 100 km over the previous year.",
      "Role-based access, multi-factor authentication and a tamper-evident audit log support internal review.",
    ],
    workflow: [
      {
        title: "See the picture",
        body: "A live map and a list view show active incidents near registered sites.",
      },
      {
        title: "Check the evidence",
        body: "Open the incident to read the source reports and the place spans that were linked.",
      },
      { title: "Brief the team", body: "Generate a daily or weekly briefing and export it as PDF or HTML." },
    ],
    faq: [
      {
        q: "Can analysts see the original reports?",
        a: "Yes. Every incident links to its original sources, and highlighted place spans show how the location was derived.",
      },
      {
        q: "Who can see our site locations?",
        a: "Only users of your tenant. Isolation is enforced in the database with row level security, and locations are excluded from platform analytics.",
      },
      {
        q: "Does the platform replace official warnings?",
        a: "No. Signals are situational awareness. Verify with local authorities and follow their guidance.",
      },
    ],
  },
  {
    slug: "travel-risk",
    title: "Travel risk",
    summary: "Know when something is reported near the cities and venues your travelers use.",
    icon: "Plane",
    problem:
      "Travel managers need to know quickly when a protest, storm or transport disruption is reported near a city where staff are staying. Generic country-level alerts are too broad to act on, and city names such as Alexandria or Birmingham exist in several countries.",
    approach: [
      "Register hotels, offices and meeting venues as assets, or draw watch zones around cities and districts.",
      "Place linking resolves a city name using the country, region and nearby places named in the same report.",
      "Country-level reports are shown as country-level and are not alerted against specific sites, so a broad report does not create false precision.",
      "Alerts can be sent to a tenant mailbox and signed webhooks, outside quiet hours.",
    ],
    workflow: [
      { title: "Define zones", body: "Draw a polygon, set a circle, or select an administrative region." },
      { title: "Receive context", body: "Alerts show the nearest registered site and the reported source." },
      {
        title: "Verify and notify",
        body: "Confirm with local authorities and notify travelers through your own channels.",
      },
    ],
    faq: [
      {
        q: "Does the platform locate individual travelers?",
        a: "No. It works with sites and zones that you define. It does not collect traveler locations.",
      },
      {
        q: "Which hazards are covered?",
        a: "Earthquakes (USGS), weather alerts (US National Weather Service) and fires (NASA FIRMS), together with news. Weather alerts are US only.",
      },
      {
        q: "Is coverage the same everywhere?",
        a: "No. News coverage is stronger for well-reported regions and thinner for small places. See the methodology page.",
      },
    ],
  },
  {
    slug: "insurance-exposure",
    title: "Insurance exposure",
    summary: "Compare reported events with insured locations by distance and uncertainty.",
    icon: "FileSearch",
    problem:
      "Underwriting and claims teams need a quick view of which insured locations sit near an event that has just been reported. A list of addresses geocoded once and a stream of unstructured reports do not meet without a shared definition of distance and certainty.",
    approach: [
      "Upload a schedule of locations. Each location keeps its source and its own location uncertainty.",
      "Exposure records store distance, containment in an event footprint where one exists, an exposure score and a level.",
      "Reports can be exported with a static map, the list of exposed locations and the disclaimer.",
      "Reviewer corrections to place links are queued, and are used for model improvement only with explicit consent.",
    ],
    workflow: [
      {
        title: "Load the schedule",
        body: "Upload locations with names, countries and criticality or value bands.",
      },
      { title: "Review exposure", body: "Sort by level, distance or group and inspect the evidence." },
      { title: "Export a report", body: "Create an HTML or PDF report for an incident or a period." },
    ],
    faq: [
      {
        q: "Is exposure a loss estimate?",
        a: "No. Exposure is a score based on distance, uncertainty and asset criticality. It is not a damage or loss model.",
      },
      {
        q: "Can we use this for claims decisions?",
        a: "Use it to prioritize attention. Decisions need verified information from official and first-party sources.",
      },
      {
        q: "How accurate are locations?",
        a: "See the evaluation tables on the methodology page, including the cases where the system fails.",
      },
    ],
  },
];

export type Industry = {
  slug: string;
  title: string;
  short: string;
  image: string;
  imageAlt: string;
  themes: string[];
  scenario: { title: string; body: string };
  workflow: string[];
  related: { title: string; href: string }[];
};

export const industries: Industry[] = [
  {
    slug: "logistics-shipping",
    title: "Logistics and shipping",
    short: "Ports, terminals, depots and crossings.",
    image: "logistics",
    imageAlt: "Aerial view of a container port at dusk",
    themes: [
      "Port and terminal closures",
      "Flooding and storm impact on road and rail",
      "Fires and industrial incidents near depots",
      "Labor actions reported near crossings",
    ],
    scenario: {
      title: "A terminal reported closed after a storm",
      body: "A regional outlet reports that a terminal is closed after a storm. The report uses the local name of the harbor. The platform links the name to the harbor, not to a town with the same name, finds three registered depots within 60 km, and raises one alert for the depot nearest to the harbor.",
    },
    workflow: [
      "Register terminals and depots with criticality",
      "Create a watch zone along the main corridor",
      "Route alerts to the control tower mailbox",
      "Review a weekly briefing by facility group",
    ],
    related: [
      { title: "Place linking", href: "/platform#place-linking" },
      { title: "Exposure scoring", href: "/platform#exposure" },
      { title: "Logistics control tower", href: "/solutions/logistics-control-tower" },
    ],
  },
  {
    slug: "manufacturing",
    title: "Manufacturing",
    short: "Plants and the suppliers around them.",
    image: "manufacturing",
    imageAlt: "Automated production line on a modern factory floor",
    themes: [
      "Fires and explosions at or near plants",
      "Power and utility outages",
      "Earthquakes near supplier regions",
      "Severe weather affecting plant access",
    ],
    scenario: {
      title: "An earthquake near a supplier region",
      body: "A magnitude 5.8 earthquake appears in the USGS feed. Within minutes, local news reports damage in two towns. The platform fuses both into one incident, shows the uncertainty circle, and lists the registered supplier sites inside it, ordered by distance and criticality.",
    },
    workflow: [
      "Upload plants and key suppliers",
      "Set rules by incident type and level",
      "Acknowledge and assign alerts to site managers",
      "Close with a recorded reason",
    ],
    related: [
      { title: "Hazard and news fusion", href: "/platform#incidents" },
      { title: "Alerts and briefings", href: "/platform#alerts" },
      { title: "Corporate security", href: "/solutions/corporate-security" },
    ],
  },
  {
    slug: "retail-consumer-goods",
    title: "Retail and consumer goods",
    short: "Distribution centers, stores and suppliers.",
    image: "retail",
    imageAlt: "Warehouse shelves stocked with packaged goods",
    themes: [
      "Distribution center disruption",
      "Severe weather in store clusters",
      "Civil unrest near store groups",
      "Supplier region incidents",
    ],
    scenario: {
      title: "Severe weather over a store cluster",
      body: "A weather alert covers several counties. The platform lists the store group inside the alert area, shows which distribution center serves them, and includes the alert in the next morning briefing.",
    },
    workflow: [
      "Group stores by region",
      "Draw watch zones for high-value clusters",
      "Send a daily briefing to regional leads",
      "Export an incident report for the review",
    ],
    related: [
      { title: "Watch zones", href: "/platform#alerts" },
      { title: "Asset upload", href: "/platform#api" },
      { title: "Logistics control tower", href: "/solutions/logistics-control-tower" },
    ],
  },
  {
    slug: "energy-utilities",
    title: "Energy and utilities",
    short: "Generation, transmission and distribution sites.",
    image: "energy",
    imageAlt: "Power transmission towers at dusk",
    themes: [
      "Wildfire near lines and substations",
      "Storm and flood impact on sites",
      "Seismic activity near generation assets",
      "Incidents near pipelines and terminals",
    ],
    scenario: {
      title: "A fire detected near transmission towers",
      body: "A satellite fire detection appears in the NASA FIRMS feed near a corridor of transmission towers. The platform raises an alert for the registered substation nearest to the detection and keeps the alert open until the detection group ages out and the status changes.",
    },
    workflow: [
      "Register substations and generation sites",
      "Create corridor watch zones",
      "Escalate unacknowledged high-level alerts automatically",
      "Review exposure after each event",
    ],
    related: [
      { title: "Exposure scoring", href: "/platform#exposure" },
      { title: "Alerts and briefings", href: "/platform#alerts" },
      { title: "Insurance exposure", href: "/solutions/insurance-exposure" },
    ],
  },
  {
    slug: "insurance",
    title: "Insurance",
    short: "Insured locations and portfolios.",
    image: "insurance",
    imageAlt: "Documents and notes on a desk during review",
    themes: [
      "Event proximity to insured locations",
      "Portfolio concentration after an event",
      "Weather alert coverage of a portfolio",
      "Reviewer-confirmed location corrections",
    ],
    scenario: {
      title: "Portfolio view after a flood report",
      body: "A flood is reported along a river. The platform shows the event footprint as an uncertainty region, and lists the locations in the uploaded schedule inside and near it, with each location's own location uncertainty beside the distance.",
    },
    workflow: [
      "Upload the schedule with a reviewed column mapping",
      "Hold ambiguous rows for review",
      "Filter exposure by level",
      "Export an HTML or PDF report",
    ],
    related: [
      { title: "Insurance exposure", href: "/solutions/insurance-exposure" },
      { title: "Exposure scoring", href: "/platform#exposure" },
      { title: "Methodology", href: "/methodology" },
    ],
  },
  {
    slug: "corporate-security",
    title: "Corporate security",
    short: "Offices, plants and facilities worldwide.",
    image: "security-ops",
    imageAlt: "Operations center with several monitors",
    themes: [
      "Civil unrest near offices",
      "Fires and building incidents",
      "Transport disruption around sites",
      "Weather and seismic events",
    ],
    scenario: {
      title: "Unrest reported in a capital city",
      body: "Several outlets report a demonstration in a capital city. The reports mention a district and a square. The platform groups them into one incident, locates it at district level with a stated uncertainty, and alerts for the office within the radius, showing the sources for verification.",
    },
    workflow: [
      "Register offices with criticality",
      "Set quiet hours and notification routes",
      "Open incident detail to review evidence",
      "Share a briefing with leadership",
    ],
    related: [
      { title: "Corporate security", href: "/solutions/corporate-security" },
      { title: "Incidents", href: "/platform#incidents" },
      { title: "Security", href: "/security" },
    ],
  },
];

export const capabilities = [
  {
    title: "Place and facility linking",
    body: "Place names in text become places and facilities with coordinates, using an entity linker, type filters and a gazetteer fallback.",
    icon: "MapPin",
    href: "/platform#place-linking",
  },
  {
    title: "Hazard and news fusion",
    body: "Earthquake, weather and fire records are combined with news reports into one incident, with every source linked.",
    icon: "Layers",
    href: "/platform#incidents",
  },
  {
    title: "Incident classification",
    body: "Each incident has a type, a severity level and a status, with a stated location level and uncertainty.",
    icon: "Tags",
    href: "/platform#incidents",
  },
  {
    title: "Asset exposure scoring",
    body: "Distance, location uncertainty, severity and asset criticality combine into an exposure level for each asset.",
    icon: "Target",
    href: "/platform#exposure",
  },
  {
    title: "Alerts, watch zones and briefings",
    body: "Rules, polygon, circle and region zones, quiet hours, escalation, and daily or weekly briefings.",
    icon: "BellRing",
    href: "/platform#alerts",
  },
  {
    title: "API and batch upload",
    body: "Upload assets in bulk, read alerts, create signed webhooks and locate text through a documented API.",
    icon: "Braces",
    href: "/developers",
  },
];

export type Plan = {
  id: string;
  name: string;
  price: number;
  assets: number;
  overageUnit: number;
  overagePrice: number;
  blurb: string;
  features: string[];
};

/** Mirrors the plans table of the demonstration environment (see data/scripts/generate_demo_business_data.py). */
export const plans: Plan[] = [
  {
    id: "starter",
    name: "Starter",
    price: 499,
    assets: 50,
    overageUnit: 25,
    overagePrice: 60,
    blurb: "For a single team monitoring a small set of sites.",
    features: [
      "Up to 50 monitored assets",
      "Alerts by email",
      "Daily and weekly briefings",
      "Watch zones",
      "Multi-factor authentication",
    ],
  },
  {
    id: "professional",
    name: "Professional",
    price: 1999,
    assets: 500,
    overageUnit: 25,
    overagePrice: 200,
    blurb: "For operations teams with regional networks.",
    features: [
      "Up to 500 monitored assets",
      "Everything in Starter",
      "API keys and signed webhooks",
      "Automatic escalation rules",
      "Audit log viewer",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: 8000,
    assets: 5000,
    overageUnit: 25,
    overagePrice: 400,
    blurb: "For global networks and several teams.",
    features: [
      "Up to 5,000 monitored assets",
      "Everything in Professional",
      "Role-based access for several teams",
      "Correction review workflow",
    ],
  },
];

export const comparison: { feature: string; values: [string, string, string] }[] = [
  { feature: "Monitored assets included", values: ["50", "500", "5,000"] },
  { feature: "Overage per additional 25 assets, per month", values: ["$60", "$200", "$400"] },
  { feature: "Place linking and incident detection", values: ["Included", "Included", "Included"] },
  { feature: "Watch zones (polygon, circle, region)", values: ["Included", "Included", "Included"] },
  { feature: "Daily and weekly briefings", values: ["Included", "Included", "Included"] },
  { feature: "Email alerts with quiet hours", values: ["Included", "Included", "Included"] },
  { feature: "Multi-factor authentication", values: ["Included", "Included", "Included"] },
  { feature: "API keys and signed webhooks", values: ["Not included", "Included", "Included"] },
  { feature: "Automatic escalation rules", values: ["Not included", "Included", "Included"] },
  { feature: "Audit log viewer", values: ["Not included", "Included", "Included"] },
  { feature: "Role-based access across teams", values: ["Not included", "Not included", "Included"] },
  { feature: "Correction review workflow", values: ["Not included", "Not included", "Included"] },
];

export const pricingFaq: FaqItem[] = [
  {
    q: "What counts as a monitored asset?",
    a: "Each active site or location that you register counts once. Archived assets do not count.",
  },
  {
    q: "What happens if we exceed the asset limit?",
    a: "Additional assets are billed in blocks of 25 at the overage price of your plan. Monitoring continues without interruption.",
  },
  {
    q: "Is there an annual option?",
    a: "Yes. In the demonstration price list, annual billing carries a 10 percent discount on the monthly equivalent.",
  },
  {
    q: "Are these real prices?",
    a: "No. They are illustrative prices for the demonstration environment. No customer is billed.",
  },
];

export const sources = [
  { name: "USGS", kind: "usgs", note: "Earthquakes, worldwide" },
  { name: "National Weather Service", kind: "nws", note: "Weather alerts, United States only" },
  { name: "NASA FIRMS", kind: "firms", note: "Satellite fire detections, worldwide" },
  { name: "GDELT", kind: "news", note: "News metadata, worldwide" },
  { name: "Wikidata", kind: "ref", note: "Entities and coordinates" },
  { name: "GeoNames", kind: "ref", note: "Gazetteer of populated places" },
  { name: "Natural Earth", kind: "ref", note: "Boundaries" },
];

export function evaluationOutcome(): string {
  return `${points(metrics.acc_161km_ambiguous, metrics.acc_161km_best_gazetteer_baseline_ambiguous)} (${pct(metrics.acc_161km_ambiguous)} against ${pct(metrics.acc_161km_best_gazetteer_baseline_ambiguous)})`;
}
