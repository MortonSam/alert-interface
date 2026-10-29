// DRAFTS for Sam and a lawyer to review (Claude, 2026-10-29). Written from what the site's code collects and does on the accounts
// branch; nothing collects an email until Sam approves both and turns ACCOUNTS_ENABLED on. Items marked [CONFIRM] are facts Sam must
// check before publishing. Listed verbatim in backend/ops/reports/accounts_2026-10-29/wording.md.

export interface LegalSection { heading: string; paragraphs: string[] }
export interface LegalDoc { title: string; status: string; updated: string; sections: LegalSection[] }

export const PRIVACY_DRAFT: LegalDoc = {
  title: "Privacy policy",
  status: "Draft for review, not in force",
  updated: "Draft of Oct 29, 2026",
  sections: [
    { heading: "The short version", paragraphs: [
      "You can read everything on Alert Interface without an account. If you make one, we keep your email address, the stocks you follow, the trade ideas you save, your email settings and when you signed in. We use them to run your account and send the emails you turn on. We don't sell them, and we don't use them for advertising.",
    ] },
    { heading: "What we collect", paragraphs: [
      "Your email address, when you ask for a sign-in link. We keep it as the name of your account.",
      "A record of each sign-in link: the address it went to, the network address (IP) it was asked from, and when it was asked for, used or expired. We use these to stop abuse, for example too many links asked for at once.",
      "A session: a random code kept in a cookie in your browser, and a scrambled copy of it on our side, with when it started and when it was last used. It keeps you signed in for up to 30 days.",
      "The stocks you follow (your watchlist), the trade ideas you save in Build a Trade with any notes you write on them, and their hypothetical results.",
      "Your email settings, and a record of each email we send you: the day, which kinds it held and what it reported on, so we never tell you the same thing twice.",
      "Questions you ask Ivy. We keep the question, Ivy's answer and a scrambled form of the network address it came from, to answer the same question faster next time and to keep the box within its limits. [CONFIRM: questions are not linked to your account today; decide whether they should be.]",
      "If you accept analytics, PostHog records how pages are used, including session replays with every typed field masked. If you decline, nothing is recorded. [CONFIRM: whether Sentry error reports are switched on in production, and what they hold.]",
    ] },
    { heading: "What we don't collect", paragraphs: [
      "No password, no payment details, no brokerage connection, no phone number and no contacts. We never see real trades: every trade on this site is hypothetical.",
    ] },
    { heading: "How we use it", paragraphs: [
      "To sign you in, to keep what you save, to score your saved trade ideas after they expire, and to send only the emails you turn on, at most one a day.",
      "To keep the site working and fair: rate limits, abuse prevention and fixing errors.",
      "Ivy's answers and research notes are written with Anthropic's models. When you ask Ivy a question, the question and the stock's facts on file are sent to Anthropic to write the answer. Your email address is never sent.",
    ] },
    { heading: "Who handles it for us", paragraphs: [
      "Vercel hosts the website. Railway runs our servers and database. Postmark sends our email. Anthropic writes Ivy's answers. PostHog records analytics, only if you accept them. Market data comes from Intrinio and the SEC; none of your information goes to them. [CONFIRM: the list is complete and each has a data processing agreement.]",
    ] },
    { heading: "Cookies", paragraphs: [
      "One cookie keeps you signed in. It can't be read by scripts on the page, it is only sent over a secure connection, and it lasts at most 30 days.",
      "Your browser also keeps your analytics choice, your recent searches and, before you sign in, the stocks you follow. When you sign in, those followed stocks move into your account and leave the browser.",
    ] },
    { heading: "Emails", paragraphs: [
      "Every email is off until you turn it on. Each one has a one-click unsubscribe link, and your settings let you change each kind. We send at most one email a day.",
      "Sign-in links are sent whenever you ask for one, and only then.",
    ] },
    { heading: "Deleting your data", paragraphs: [
      "In your settings, Delete my account removes your account, your email address, your followed stocks, your saved trades and their results, your email settings and history, your sign-in records and your sessions, all at once. It can't be undone.",
      "Copies in our database backups expire within [CONFIRM: Railway's backup retention] days.",
    ] },
    { heading: "How long we keep it", paragraphs: [
      "Until you delete your account. Used and expired sign-in links are removed after [CONFIRM: retention, for example 30 days].",
    ] },
    { heading: "Children", paragraphs: ["The site is not meant for anyone under 18, and we don't knowingly keep their information."] },
    { heading: "Changes and contact", paragraphs: [
      "If this policy changes in a way that matters, we'll say so on this page and by email to account holders before it takes effect.",
      "Questions: [CONFIRM: contact address]. Postal address: MAILING_ADDRESS.",
    ] },
  ],
};

export const TERMS_DRAFT: LegalDoc = {
  title: "Terms of use",
  status: "Draft for review, not in force",
  updated: "Draft of Oct 29, 2026",
  sections: [
    { heading: "What Alert Interface is", paragraphs: [
      "Alert Interface explains public companies and their stocks for learning. Ivy doesn't make buy or sell calls. Nothing here is investment, tax or legal advice, an offer, or a recommendation to buy, sell or hold any security.",
    ] },
    { heading: "Hypothetical only", paragraphs: [
      "Every trade on this site is hypothetical. Saved ideas, their results and Ivy's picks are never executed, and no money changes hands. Past results, real or hypothetical, say nothing certain about the future.",
    ] },
    { heading: "Data and accuracy", paragraphs: [
      "Figures come from dated sources such as SEC filings and licensed market data, and each is shown with its date. Some data is delayed. We check figures and Ivy's sentences, but mistakes can still happen; check anything that matters to you with the source.",
    ] },
    { heading: "Your account", paragraphs: [
      "You need an account only to save, to ask Ivy and to get emails. Keep access to your email secure, because a sign-in link opens your account. You can delete your account at any time from your settings.",
    ] },
    { heading: "Fair use", paragraphs: [
      "Don't misuse the site: no automated scraping beyond normal use, no attempts to get around limits or security, and no use that breaks the law. We may limit or close an account that does.",
    ] },
    { heading: "Ivy's answers", paragraphs: [
      "Ivy answers only from the facts on file for the stock you ask about and may decline a question. Answers are written by an AI model and checked, but they can be wrong. They are not advice.",
    ] },
    { heading: "Our liability", paragraphs: [
      "The site is provided as is. To the extent the law allows, we are not liable for losses from using it or relying on it. [CONFIRM: a lawyer drafts this section, the governing law and the dispute terms.]",
    ] },
    { heading: "Changes", paragraphs: ["We'll post changes here and email account holders before a change that matters takes effect."] },
  ],
};
