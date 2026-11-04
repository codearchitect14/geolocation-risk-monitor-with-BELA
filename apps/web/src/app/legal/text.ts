import type { LegalSection } from "./doc";

export const PRIVACY: LegalSection[] = [
  {
    heading: "1. Who we are",
    body: [
      "Meridian Signal is a demonstration product. This policy explains how personal data is handled in the demonstration environment. Questions can be sent through the contact form on this site.",
    ],
  },
  {
    heading: "2. What we collect",
    body: [
      "Contact requests: the name, work email address, organization, role, industry and message you enter, the time of the request and your consent to be contacted.",
      "Newsletter: your email address, and the time you confirmed the subscription. We send a confirmation message first and subscribe you only after you follow the link in it.",
      "Accounts: for people who are given an account, the name, email address, role, a salted hash of the password, and sign-in and security events such as failed attempts. Authenticator secrets are stored encrypted.",
      "Technical data: server logs record the time, address, request path and result of requests for security and troubleshooting.",
      "Customer asset data: tenants upload the names and locations of their sites. This data is visible only to users of that tenant and is not used in platform analytics.",
    ],
  },
  {
    heading: "3. Why we use it",
    body: [
      "To reply to your request or to send the newsletter you asked for.",
      "To operate accounts, keep them secure and investigate abuse, including rate limiting and an audit log.",
      "To keep the service working and to find faults.",
      "We do not sell personal data, and we do not use it for advertising or for profiling.",
    ],
  },
  {
    heading: "4. Legal bases",
    body: [
      "Where data protection law requires a legal basis, we rely on consent for contact requests and the newsletter, on performance of an agreement for accounts, and on legitimate interests for security and operation of the service.",
    ],
  },
  {
    heading: "5. Sharing",
    body: [
      "Personal data is processed by the systems that run the demonstration environment. Email is delivered through the mail service configured for the environment. We do not share personal data with advertising or analytics providers. We may disclose data where the law requires it.",
    ],
  },
  {
    heading: "6. Retention",
    body: [
      "Contact requests and newsletter records are kept while they are needed for the purpose above and are deleted on request. Audit log entries are kept for the period set for the environment, because they are designed to be tamper-evident. Server logs are rotated.",
    ],
  },
  {
    heading: "7. Your rights",
    body: [
      "Depending on where you live, you may have the right to access, correct, delete or export your personal data, to object to or restrict processing, and to withdraw consent at any time. To exercise a right, use the contact form and say which right you wish to use. You may also complain to your data protection authority.",
    ],
  },
  {
    heading: "8. Security",
    body: [
      "Traffic is encrypted. Access is limited by role, and tenant data is isolated in the database. No system is free of risk, and this is a demonstration environment that should not hold sensitive production data.",
    ],
  },
  {
    heading: "9. International transfers",
    body: [
      "Data is processed where the environment is hosted. If you contact us from another country, your data will be transferred to that location.",
    ],
  },
  {
    heading: "10. Children",
    body: ["The site is intended for business users and is not directed at children."],
  },
  {
    heading: "11. Changes",
    body: ["We will update the date at the top of this page when the policy changes."],
  },
];

export const TERMS: LegalSection[] = [
  {
    heading: "1. Demonstration environment",
    body: [
      "This site and the application behind it are a demonstration. Prices, plans and customer scenarios are illustrative, and data labeled synthetic or demo data is generated. Availability is not guaranteed.",
    ],
  },
  {
    heading: "2. Not an official warning service",
    body: [
      "Signals are situational awareness derived from public news and public data feeds. They are not official warnings. Verify with local authorities and follow their guidance. Do not rely on the service as the only basis for decisions about safety, health or property.",
    ],
  },
  {
    heading: "3. Accounts",
    body: [
      "You are responsible for activity under your account and for keeping credentials and authenticator devices secure. Tell us promptly about suspected misuse. Administrators must use multi-factor authentication.",
    ],
  },
  {
    heading: "4. Acceptable use",
    body: [
      "You agree not to attempt to gain unauthorized access, to probe other tenants' data, to overload the service, to bypass rate limits, to use the service to track individuals, or to submit unlawful content. Automated access must use API keys and respect rate limits.",
    ],
  },
  {
    heading: "5. Your data",
    body: [
      "You keep your rights in the data you upload. You grant us the permission needed to host and process it to provide the service. Corrections you submit are used to improve models only if you give explicit consent.",
    ],
  },
  {
    heading: "6. Third-party data",
    body: [
      "The service uses public data from sources including USGS, the National Weather Service, NASA FIRMS, GDELT, Wikidata, GeoNames and Natural Earth. Each source has its own terms. We do not guarantee the accuracy, completeness or timeliness of third-party data or of results derived from it.",
    ],
  },
  {
    heading: "7. Intellectual property",
    body: [
      "The software, text and design of the service belong to their owners and are licensed to you only for use of the service. Third-party data keeps its own license.",
    ],
  },
  {
    heading: "8. Disclaimer",
    body: [
      "The service is provided as is and as available, without warranties of any kind, to the extent the law allows. Location and exposure results are estimates and can be wrong; the methodology page lists known failure rates.",
    ],
  },
  {
    heading: "9. Limitation of liability",
    body: [
      "To the extent the law allows, we are not liable for indirect or consequential loss, or for loss arising from reliance on estimates produced by the service. Nothing in these terms limits liability that cannot be limited by law.",
    ],
  },
  {
    heading: "10. Suspension and termination",
    body: [
      "We may suspend access that breaches these terms or threatens the security of the service. You may stop using the service at any time.",
    ],
  },
  {
    heading: "11. Changes and governing law",
    body: [
      "We may update these terms and will change the date above when we do. The terms are governed by the law of the place where the operator of the environment is established, unless mandatory law of your location says otherwise.",
    ],
  },
];

export const COOKIES: LegalSection[] = [
  {
    heading: "1. Summary",
    body: [
      "This site does not use analytics, advertising or tracking cookies. It stores only the small items needed to work.",
    ],
  },
  {
    heading: "2. What is stored",
    body: [
      "Language choice (local storage, key ms_locale): remembers the interface language you selected. It is stored in your browser and is not sent to the server.",
      "Notice acknowledgement (local storage, key ms_notice_ack): remembers that you dismissed the notice about storage.",
      "Session cookies (ms_access, ms_refresh, ms_csrf): set only when you sign in. They keep you signed in and protect requests against forgery. The first two cannot be read by scripts.",
    ],
  },
  {
    heading: "3. Third parties",
    body: [
      "The site loads fonts, images and map outlines from its own server. It does not load third-party scripts, trackers or fonts.",
    ],
  },
  {
    heading: "4. Your choices",
    body: [
      "You can clear site data in your browser at any time. If you block the session cookies, you will not be able to sign in. Because only essential storage is used, no consent banner with choices is shown; the notice on this site is informational.",
    ],
  },
];
