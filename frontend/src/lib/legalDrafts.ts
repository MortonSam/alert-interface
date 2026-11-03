// DRAFTS for Sam and a lawyer to review (Claude, 2026-10-29; the privacy policy rewritten 2026-11-02 to cover visitors without an account). Written from what the site's code collects and does on the accounts
// branch; nothing collects an email until Sam approves both and turns ACCOUNTS_ENABLED on. Items marked [CONFIRM] are facts Sam must
// check before publishing. Listed verbatim in backend/ops/reports/accounts_2026-10-29/wording.md.

export interface LegalSection { heading: string; paragraphs: string[] }
export interface LegalDoc { title: string; status: string; updated: string; sections: LegalSection[] }

export const PRIVACY_DRAFT: LegalDoc = {
  title: "Privacy policy",
  status: "Draft for review, not in force",
  updated: "Draft of Nov 2, 2026",
  sections: [
    { heading: "The short version", paragraphs: [
      "You can read everything on Alert Interface without an account. Even then, a few things are recorded: our hosting providers log each request, we keep your network address for a day's limits when you use Build a Trade, Ask Ivy or a research note, and analytics run only if you accept them. If you make an account, we also keep your email address, the stocks you follow, the trade ideas you save, your email settings and when you signed in. We don't sell any of it, and we don't use it for advertising.",
    ] },
    { heading: "Without an account", paragraphs: [
      "Request logs. Vercel, which hosts the website, and Railway, which runs our servers, log each request: the page or address asked for, the time, your network address (IP) and your browser's description of itself. [CONFIRM: How long do Vercel and Railway keep these logs on our plans?]",
      "Limits. When you ask Build a Trade for a draft, ask Ivy a question or ask for a research note to be written, we keep your network address with the times you used it, so each visitor stays within the day's limits. [CONFIRM: Today all three limits keep the address exactly as it is, and the record is never deleted, though only the last day's times are read. Should it be scrambled and deleted after a day before launch?]",
      "Questions you ask Ivy. We keep the question, Ivy's answer and a scrambled form of the network address it came from, to answer the same question faster next time and to keep the box within its limits. [CONFIRM: Should questions be linked to the account of a signed-in person? They aren't today.]",
      "Build a Trade drafts. The stock, direction and risk level you choose are kept with the draft Ivy writes, and the same draft is shown to anyone who makes the same choice that day. Nothing about you is kept with it.",
      "Error reports. When something breaks, an error report can be sent to Sentry with the page address, your browser's description and your network address. [CONFIRM: Is Sentry switched on in production (SENTRY_DSN on Railway, and on Vercel for the website)? If it isn't, this paragraph comes out.]",
      "Analytics, only if you accept them. PostHog records how pages are used, including session replays with every typed field masked. A link in one of our emails carries a tag naming the kind of email, so analytics can count visits that came from it. If you decline, nothing is recorded and the tag is ignored.",
      "Your browser keeps your analytics choice, your recent searches, a copy of the site's counts so the home page loads quickly, and, before you sign in, the stocks you follow. None of these leave your browser except the followed stocks, which move into your account when you sign in.",
    ] },
    { heading: "With an account", paragraphs: [
      "Your email address, when you ask for a sign-in link. We keep it as the name of your account.",
      "A record of each sign-in link: the address it went to, the network address it was asked from, and when it was asked for, used or expired. We use these to stop abuse, for example too many links asked for at once.",
      "A session: a random code kept in a cookie in your browser, and a scrambled copy of it on our side, with when it started and when it was last used. It keeps you signed in for up to 30 days.",
      "The stocks you follow (your watchlist), the trade ideas you save in Build a Trade with any notes you write on them, and their hypothetical results.",
      "Your email settings, and a record of each email we send you: the day, which kinds it held and what it reported on, so we never tell you the same thing twice.",
    ] },
    { heading: "What we don't collect", paragraphs: [
      "No password, no payment details, no brokerage connection, no phone number and no contacts. We never see real trades: every trade on this site is hypothetical.",
    ] },
    { heading: "How we use it", paragraphs: [
      "To sign you in, to keep what you save, to score your saved trade ideas after they expire, and to send only the emails you turn on, at most one a day.",
      "To keep the site working and fair: rate limits, abuse prevention and fixing errors.",
      "Ivy's answers, research notes and Build a Trade drafts are written with Anthropic's models. When you ask Ivy a question, the question and the stock's facts on file are sent to Anthropic to write the answer. Your email address and your network address are never sent.",
    ] },
    { heading: "Who handles it for us", paragraphs: [
      "Vercel hosts the website. Railway runs our servers and database. Postmark sends our email. Anthropic writes Ivy's answers, notes and drafts. PostHog records analytics, only if you accept them. Sentry receives error reports. Market data comes from Intrinio and the SEC, and none of your information goes to them. [CONFIRM: Is this list complete, and does each one have a data processing agreement with us?]",
    ] },
    { heading: "Cookies", paragraphs: [
      "One cookie keeps you signed in. It can't be read by scripts on the page, it is only sent over a secure connection, and it lasts at most 30 days.",
      "If you accept analytics, PostHog sets its own cookie and browser storage to tell one visit from the next. If you decline, it sets none.",
    ] },
    { heading: "Emails", paragraphs: [
      "Every email is off until you turn it on. Each one has a one-click unsubscribe link, and your settings let you change each kind. We send at most one email a day.",
      "Sign-in links are sent whenever you ask for one, and only then.",
      "Our emails carry no tracking pixel, and their links aren't rewritten to track clicks. A link to our site carries a tag naming the kind of email, which analytics reads only if you've accepted analytics on the site.",
      "If an email to your address bounces for good or is reported as spam, we stop emailing that address, and we keep the address on a do-not-email list so it isn't emailed again, even after the account is deleted. Write to privacy@alertinterface.com from that address to be taken off the list.",
    ] },
    { heading: "Deleting your data", paragraphs: [
      "In your settings, Delete my account removes your account, your email address, your followed stocks, your saved trades and their results, your email settings and history, your sign-in records and your sessions, all at once. It can't be undone. The one exception is the do-not-email list above.",
      "Copies in our database backups expire within [CONFIRM: How many days does Railway keep database backups on our plan?] days.",
      "Without an account, you can ask us to delete the questions you asked Ivy or the records kept for limits by writing to privacy@alertinterface.com with the day and roughly the time.",
    ] },
    { heading: "How long we keep it", paragraphs: [
      "Account data, until you delete your account. Used and expired sign-in links are removed after [CONFIRM: How long should used and expired sign-in links be kept? 30 days is a common choice.].",
    ] },
    { heading: "Children", paragraphs: ["The site is not meant for anyone under 18, and we don't knowingly keep their information."] },
    { heading: "Changes and contact", paragraphs: [
      "If this policy changes in a way that matters, we'll say so on this page and by email to account holders before it takes effect.",
      "Questions: privacy@alertinterface.com. Postal address: MAILING_ADDRESS. [CONFIRM: What postal address goes here and in every email's footer?]",
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
      "Every trade on this site is hypothetical. Saved ideas and their results are never executed, and no money changes hands. Past results, real or hypothetical, say nothing certain about the future.",
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
      "The site is provided as is. To the extent the law allows, we are not liable for losses from using it or relying on it. [CONFIRM: Will a lawyer write this section, and which state's law and which way of settling disputes should it name?]",
    ] },
    { heading: "Changes", paragraphs: ["We'll post changes here and email account holders before a change that matters takes effect."] },
  ],
};
